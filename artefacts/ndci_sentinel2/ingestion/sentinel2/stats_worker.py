"""
Worker: extração de estatísticas agregadas por lagoa/mês (Sentinel-2 via GEE).

Este é o worker ausente identificado no relatório técnico do eyefish.
O eyefish tinha o endpoint POST /api/workers/run-gee-qualidade-agua mas a
função ingest_gee_qualidade_agua não estava implementada no módulo ambiental.py.

Este worker implementa o que estava faltando:
  - Usa ee.Image.reduceRegion() para agregar estatísticas pixel-level
  - Calcula mean (média), p90 (percentil 90) para NDCI
  - Salva em ndci_water_quality com o mesmo schema de gee_qualidade_agua

Pipeline por lagoa × mês:
  1. S2_SR_HARMONIZED filtrado por data e geometria
  2. SCL cloud mask → mediana mensal
  3. Máscara de água (NDWI > -0.1)
  4. reduceRegion(ee.Reducer.mean()) → ndci_mean, ndti_mean, ndwi_mean
  5. reduceRegion(ee.Reducer.percentile([90])) → ndci_p90
  6. pixelArea().updateMask() → n_pixels (contagem de pixels válidos)
  7. Salvo em ndci_water_quality
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import datetime
from typing import Any

from config import LAGOAS, SENTINEL2_START_YEAR, WATER_MASK_THRESHOLD
from ingestion.gee_auth import init_ee
from ingestion.sentinel2.cloud_mask import cloud_mask_s2
from ingestion.sentinel2.band_math import add_water_indices, water_mask
from storage.database import SessionLocal
from storage.models import WaterQualityRecord
from storage.repositories.water_quality import WaterQualityRepository

logger = logging.getLogger(__name__)

# Escala em metros para reduceRegion (deve ser ≥ resolução da banda mais grossa)
# B5 tem 20 m → usamos 20 m como escala de redução.
_REDUCE_SCALE_M: int = 20

# Número máximo de pixels por operação (proteção contra timeout GEE)
_MAX_PIXELS: int = 1_000_000


def _safe_float(val: Any) -> float | None:
    """Converte resultado do GEE para float, retorna None em caso de erro."""
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
    Coleta estatísticas NDCI/NDTI/NDWI para as lagoas via reduceRegion.

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
    lagoas_cfg = {k: v for k, v in LAGOAS.items() if k in (lagoas or LAGOAS)}

    saved, skipped, errors = 0, 0, []

    # Pipeline base: cloud mask + índices calculados uma vez para todas as queries
    s2_base = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .map(cloud_mask_s2)
        .map(add_water_indices)
    )

    db   = SessionLocal()
    repo = WaterQualityRepository(db)

    try:
        for lagoa_name, lagoa_cfg in lagoas_cfg.items():
            geom = ee.Geometry.Polygon([lagoa_cfg["polygon"]])

            for year in range(ano_inicio, ano_fim + 1):
                mes_fim = now.month if year == now.year else 12

                for mes in range(1, mes_fim + 1):
                    if not force:
                        existing = (
                            db.query(WaterQualityRecord)
                            .filter_by(satellite="sentinel2", lagoa=lagoa_name, ano=year, mes=mes)
                            .first()
                        )
                        if existing:
                            skipped += 1
                            continue

                    try:
                        ultimo = calendar.monthrange(year, mes)[1]
                        d0 = f"{year}-{mes:02d}-01"
                        d1 = f"{year}-{mes:02d}-{ultimo}"

                        monthly = (
                            s2_base
                            .filterDate(d0, d1)
                            .filterBounds(geom)
                        )

                        n_images = monthly.size().getInfo()
                        if n_images == 0:
                            logger.debug(
                                "Stats: sem imagens — %s %d-%02d", lagoa_name, year, mes
                            )
                            skipped += 1
                            continue

                        composite = monthly.median()
                        water_img = water_mask(composite, WATER_MASK_THRESHOLD)

                        # ── Médias via ee.Reducer.mean() ──────────────────────
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

                        # ── Percentil 90 do NDCI ──────────────────────────────
                        p90_result = water_img.select("NDCI").reduceRegion(
                            reducer=ee.Reducer.percentile([90]),
                            geometry=geom,
                            scale=_REDUCE_SCALE_M,
                            maxPixels=_MAX_PIXELS,
                            bestEffort=True,
                        ).getInfo()
                        ndci_p90 = _safe_float(p90_result.get("NDCI_p90"))

                        # ── Floating Algae Index (FAI) ─────────────────────────
                        # FAI = B8 - (B4 + (B11 - B4) × (842 - 665) / (1610 - 665))
                        # Sentinel-2 SR tem B11 (SWIR1 a 1610 nm, 20 m).
                        # Se B11 não estiver disponível no composite, skipa FAI.
                        fai_mean: float | None = None
                        try:
                            b4  = composite.select("B4").toFloat()
                            b8  = composite.select("B8").toFloat()
                            b11 = composite.select("B11").toFloat()

                            # Interpolação linear na linha de base NIR
                            nir_baseline = b4.add(
                                b11.subtract(b4).multiply((842 - 665) / (1610 - 665))
                            )
                            fai_img = b8.subtract(nir_baseline).rename("FAI")
                            fai_img = fai_img.updateMask(water_img.select("NDWI").gt(WATER_MASK_THRESHOLD))

                            fai_result = fai_img.reduceRegion(
                                reducer=ee.Reducer.mean(),
                                geometry=geom,
                                scale=_REDUCE_SCALE_M,
                                maxPixels=_MAX_PIXELS,
                                bestEffort=True,
                            ).getInfo()
                            fai_mean = _safe_float(fai_result.get("FAI"))
                        except Exception:
                            pass  # FAI é opcional

                        # ── Contagem de pixels válidos ─────────────────────────
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

                        # ── Persiste ──────────────────────────────────────────
                        repo.upsert(
                            satellite="sentinel2",
                            lagoa=lagoa_name,
                            ano=year,
                            mes=mes,
                            ndci_mean=ndci_mean,
                            ndci_p90=ndci_p90,
                            ndti_mean=ndti_mean,
                            fai_mean=fai_mean,
                            ndwi_mean=ndwi_mean,
                            n_pixels=n_pixels,
                        )
                        saved += 1
                        logger.info(
                            "Stats: %s %d-%02d — ndci=%.4f n_pixels=%s",
                            lagoa_name, year, mes,
                            ndci_mean or 0, n_pixels,
                        )

                    except Exception as exc:
                        db.rollback()
                        msg = f"{lagoa_name}/{year}-{mes:02d}: {exc}"
                        errors.append(msg)
                        logger.warning("Stats erro: %s", msg)

    finally:
        db.close()

    return {"saved": saved, "skipped": skipped, "errors": errors}


# ── Wrapper async ─────────────────────────────────────────────────────────────

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
