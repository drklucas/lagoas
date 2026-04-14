"""
Worker: extração de estatísticas por imagem individual (Sentinel-2 via GEE).

Metodologia alinhada com Pi & Guasselli (SBSR 2025):
  - Coleta por imagem individual (não composição mensal)
  - Buffer negativo de borda aplicado antes do reduceRegion
  - Pré-filtro CLOUDY_PIXEL_PERCENTAGE < 20% para descartar cenas nebulosas
  - Critério de pixels válidos mínimos por lagoa
  - Salva em ndci_image_records (granularidade por imagem)
  - Deriva agregados mensais em ndci_water_quality via SQL GROUP BY

Pipeline por lagoa × imagem:
  1. S2_SR_HARMONIZED filtrado por data, geometria e CLOUDY_PIXEL_PERCENTAGE < 20
  2. SCL cloud mask (remove sombras, nuvens, cirrus — mantém classe 4 VEGETATION)
  3. Índices calculados: NDCI, NDTI, NDWI, FAI
  4. Buffer negativo aplicado ao polígono → geom erodida
  5. Máscara de água (NDWI > threshold OR FAI > 0)
  6. reduceRegion(mean + percentile) na geom erodida
  7. Filtro por MIN_VALID_PIXELS → imagens com cobertura insuficiente descartadas
  8. Salvo em ndci_image_records
  9. Agregação mensal atualizada em ndci_water_quality
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

from config import ACTIVE_LAGOAS, LAGOAS, SENTINEL2_START_YEAR, WATER_MASK_THRESHOLD
from ingestion.gee_auth import init_ee
from ingestion.sentinel2.cloud_mask import cloud_mask_s2
from ingestion.sentinel2.band_math import add_water_indices, water_mask
from storage.database import SessionLocal
from storage.models import WaterQualityRecord
from storage.repositories.image_records import ImageRecordRepository
from storage.repositories.water_quality import WaterQualityRepository

logger = logging.getLogger(__name__)

# Escala em metros para reduceRegion (≥ resolução da banda mais grossa — B5 a 20 m)
_REDUCE_SCALE_M: int = 20

# Número máximo de pixels por operação (proteção contra timeout GEE)
_MAX_PIXELS: int = 1_000_000

# Percentual máximo de nuvens por cena — pré-filtro nos metadados Sentinel-2
_MAX_CLOUD_PCT: float = 20.0

# Pixels válidos mínimos por lagoa após cloud mask + water mask.
# Proporcional à área esperada com o buffer negativo aplicado.
# Lagoas grandes (Barros, Quadros, Itapeva): valores maiores;
# Lagoas pequenas (Caconde, Peixoto): valores menores.
_MIN_VALID_PIXELS: dict[str, int] = {
    "Lagoa dos Barros":   2000,
    "Lagoa dos Quadros":  3000,
    "Lagoa Itapeva":      2000,
    "Lagoa de Tramandaí": 1000,
    "Lagoa do Armazém":   1000,
    "Lagoa do Peixoto":    300,
    "Lagoa Caconde":       100,
}
_MIN_VALID_PIXELS_DEFAULT: int = 200


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _sync_collect_stats(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    force: bool = False,
) -> dict:
    """
    Coleta estatísticas NDCI/NDTI/NDWI por imagem individual via GEE.

    Para cada imagem válida (cobertura de nuvens < 20%, pixels válidos >=
    mínimo por lagoa), salva em ndci_image_records. Ao final de cada mês,
    deriva o agregado mensal e atualiza ndci_water_quality.

    Args:
        ano_inicio: primeiro ano a processar
        ano_fim:    último ano (default: ano atual)
        lagoas:     lista de lagoas específicas (default: todas)
        force:      se True, sobrescreve registros já existentes

    Returns:
        {"saved": int, "skipped": int, "errors": list[str]}
    """
    if not init_ee():
        return {
            "saved": 0,
            "skipped": 0,
            "errors": ["GEE init failed — verifique GEE_SERVICE_ACCOUNT_KEY"],
        }

    import ee

    now        = datetime.utcnow()
    ano_fim    = ano_fim or now.year
    allowed    = lagoas or ACTIVE_LAGOAS or list(LAGOAS)
    lagoas_cfg = {k: v for k, v in LAGOAS.items() if k in allowed}

    saved, skipped, errors = 0, 0, []

    # Pipeline base: cloud mask SCL + índices (incluindo FAI para water mask)
    s2_base = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _MAX_CLOUD_PCT))
        .map(cloud_mask_s2)
        .map(add_water_indices)
    )

    db        = SessionLocal()
    img_repo  = ImageRecordRepository(db)
    wq_repo   = WaterQualityRepository(db)

    try:
        for lagoa_name, lagoa_cfg in lagoas_cfg.items():
            geom_raw  = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
            buffer_m  = lagoa_cfg.get("buffer_negativo_m", 0)
            geom      = geom_raw.buffer(-buffer_m) if buffer_m > 0 else geom_raw
            min_pix   = _MIN_VALID_PIXELS.get(lagoa_name, _MIN_VALID_PIXELS_DEFAULT)

            d0 = f"{ano_inicio}-01-01"
            mes_fim_ultimo = now.month if ano_fim == now.year else 12
            d1 = f"{ano_fim}-{mes_fim_ultimo:02d}-{_last_day(ano_fim, mes_fim_ultimo)}"

            col = (
                s2_base
                .filterDate(d0, d1)
                .filterBounds(geom_raw)   # filtro espacial no polígono completo
            )

            n_images = col.size().getInfo()
            if n_images == 0:
                logger.debug("Stats: sem imagens — %s %s..%s", lagoa_name, d0, d1)
                continue

            logger.info(
                "Stats: %s — %d imagens a processar (%s..%s)",
                lagoa_name, n_images, d0, d1,
            )

            image_list = col.toList(n_images)
            _last_aggregated_month: tuple[int, int] | None = None  # (ano, mes)
            _saved_this_month: int = 0
            saved_this_lagoa: int = 0

            for i in range(n_images):
                img       = ee.Image(image_list.get(i))
                date_str  = img.date().format("YYYY-MM-dd").getInfo()
                img_date  = date.fromisoformat(date_str)
                cloud_pct = _safe_float(img.get("CLOUDY_PIXEL_PERCENTAGE").getInfo())

                # Agrega o mês anterior ao entrar num mês novo — só se salvou algo.
                current_month = (img_date.year, img_date.month)
                if _last_aggregated_month and current_month != _last_aggregated_month:
                    if _saved_this_month > 0:
                        _update_monthly_aggregates(
                            lagoa_name, wq_repo, img_repo,
                            _last_aggregated_month[0], _last_aggregated_month[0],
                            mes_unico=_last_aggregated_month[1],
                        )
                        logger.info(
                            "Stats: agregação mensal %s %d-%02d concluída",
                            lagoa_name, *_last_aggregated_month,
                        )
                    _saved_this_month = 0
                _last_aggregated_month = current_month

                if not force and img_repo.exists("sentinel2", lagoa_name, img_date):
                    skipped += 1
                    continue

                try:
                    water_img = water_mask(img, WATER_MASK_THRESHOLD)

                    # ── Contagem de pixels válidos ────────────────────────────
                    n_pixels: int | None = None
                    try:
                        pixel_count = (
                            water_img.select("NDCI")
                            .unmask(0)
                            .mask()
                            .reduceRegion(
                                reducer=ee.Reducer.sum(),
                                geometry=geom,
                                scale=_REDUCE_SCALE_M,
                                maxPixels=_MAX_PIXELS,
                                bestEffort=True,
                            ).getInfo()
                        )
                        n_pixels = int(pixel_count.get("NDCI", 0) or 0)
                    except Exception:
                        pass

                    if n_pixels is not None and n_pixels < min_pix:
                        logger.debug(
                            "Stats: descartando %s %s — pixels=%d < min=%d",
                            lagoa_name, date_str, n_pixels, min_pix,
                        )
                        skipped += 1
                        continue

                    # ── Médias ────────────────────────────────────────────────
                    means = water_img.select(["NDCI", "NDTI", "NDWI"]).reduceRegion(
                        reducer=ee.Reducer.mean(),
                        geometry=geom,
                        scale=_REDUCE_SCALE_M,
                        maxPixels=_MAX_PIXELS,
                        bestEffort=True,
                    ).getInfo()

                    ndci_mean = _safe_float(means.get("NDCI"))
                    ndti_mean = _safe_float(means.get("NDTI"))
                    ndwi_mean = _safe_float(means.get("NDWI"))

                    # ── Percentis NDCI ────────────────────────────────────────
                    pct_result = water_img.select("NDCI").reduceRegion(
                        reducer=ee.Reducer.percentile([10, 90]),
                        geometry=geom,
                        scale=_REDUCE_SCALE_M,
                        maxPixels=_MAX_PIXELS,
                        bestEffort=True,
                    ).getInfo()
                    ndci_p90 = _safe_float(pct_result.get("NDCI_p90"))
                    ndci_p10 = _safe_float(pct_result.get("NDCI_p10"))

                    # ── FAI ───────────────────────────────────────────────────
                    fai_mean: float | None = None
                    try:
                        fai_result = water_img.select("FAI").reduceRegion(
                            reducer=ee.Reducer.mean(),
                            geometry=geom,
                            scale=_REDUCE_SCALE_M,
                            maxPixels=_MAX_PIXELS,
                            bestEffort=True,
                        ).getInfo()
                        fai_mean = _safe_float(fai_result.get("FAI"))
                    except Exception:
                        pass

                    # ── Persiste ImageRecord ──────────────────────────────────
                    img_repo.upsert(
                        satellite="sentinel2",
                        lagoa=lagoa_name,
                        data=img_date,
                        ndci_mean=ndci_mean,
                        ndci_p90=ndci_p90,
                        ndci_p10=ndci_p10,
                        ndti_mean=ndti_mean,
                        ndwi_mean=ndwi_mean,
                        fai_mean=fai_mean,
                        n_pixels=n_pixels,
                        cloud_pct=cloud_pct,
                    )
                    saved += 1
                    saved_this_lagoa += 1
                    _saved_this_month += 1
                    logger.info(
                        "Stats: %s %s — ndci=%.4f n_pixels=%s cloud=%.1f%%",
                        lagoa_name, date_str,
                        ndci_mean or 0, n_pixels, cloud_pct or 0,
                    )

                except Exception as exc:
                    db.rollback()
                    msg = f"{lagoa_name}/{date_str}: {exc}"
                    errors.append(msg)
                    logger.warning("Stats erro: %s", msg)

            # ── Agrega o último mês da lagoa — só se teve saves nele ─────────
            if _saved_this_month > 0 and _last_aggregated_month:
                _update_monthly_aggregates(
                    lagoa_name, wq_repo, img_repo,
                    _last_aggregated_month[0], _last_aggregated_month[0],
                    mes_unico=_last_aggregated_month[1],
                )
                logger.info(
                    "Stats: agregação mensal %s %d-%02d concluída",
                    lagoa_name, *_last_aggregated_month,
                )
            elif saved_this_lagoa == 0:
                logger.info("Stats: %s sem novos registros — agregação ignorada", lagoa_name)

    finally:
        db.close()

    return {"saved": saved, "skipped": skipped, "errors": errors}


def _update_monthly_aggregates(
    lagoa: str,
    wq_repo: WaterQualityRepository,
    img_repo: ImageRecordRepository,
    ano_inicio: int,
    ano_fim: int,
    mes_unico: int | None = None,
) -> None:
    """
    Recalcula ndci_water_quality a partir dos ImageRecords desta lagoa.

    Se mes_unico for fornecido, atualiza apenas aquele mês (chamada incremental
    ao final de cada mês durante a coleta). Caso contrário, recalcula todos
    os meses no intervalo ano_inicio..ano_fim.

    Usa GROUP BY SQL — não faz chamadas ao GEE.
    """
    monthly = img_repo.get_monthly_aggregation(lagoa=lagoa, satellite="sentinel2")
    for row in monthly:
        if not (ano_inicio <= row["ano"] <= ano_fim):
            continue
        if mes_unico is not None and row["mes"] != mes_unico:
            continue
        try:
            wq_repo.upsert(
                satellite="sentinel2",
                lagoa=lagoa,
                ano=row["ano"],
                mes=row["mes"],
                ndci_mean=row["ndci_mean"],
                ndci_p90=row["ndci_p90"],
                ndti_mean=row["ndti_mean"],
                fai_mean=row["fai_mean"],
                ndwi_mean=row["ndwi_mean"],
                n_pixels=row["n_pixels"],
            )
        except Exception as exc:
            logger.warning(
                "Falha ao atualizar agregado mensal %s %d-%02d: %s",
                lagoa, row["ano"], row["mes"], exc,
            )


def _last_day(year: int, month: int) -> int:
    import calendar
    return calendar.monthrange(year, month)[1]


# ── Wrapper async ──────────────────────────────────────────────────────────────

async def collect_stats(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Wrapper async para _sync_collect_stats (roda em executor de thread)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _sync_collect_stats(ano_inicio, ano_fim, lagoas, force),
    )
