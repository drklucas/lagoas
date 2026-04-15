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
  6. reduceRegion combinado (mean + percentile + count) em 1 única chamada GEE
  7. Filtro por MIN_VALID_PIXELS → imagens com cobertura insuficiente descartadas
  8. Salvo em ndci_image_records
  9. Agregação mensal atualizada em ndci_water_quality

Paralelismo:
  - Até _MAX_LAGOA_WORKERS lagoas processadas simultaneamente via ThreadPoolExecutor
  - _gee_semaphore limita getInfo() concorrentes ao GEE (proteção contra rate limit)
  - Retry exponencial automático em erros de quota GEE
  - Cada imagem faz 2 getInfo() (era 7) — metadados + reducer combinado
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import date, datetime
from typing import Any

from config import ACTIVE_LAGOAS, LAGOAS, SENTINEL2_START_YEAR, WATER_MASK_THRESHOLD
from ingestion.gee_auth import init_ee
from ingestion.sentinel2.cloud_mask import cloud_mask_s2
from ingestion.sentinel2.band_math import add_water_indices, water_mask
from storage.database import SessionLocal
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
_MIN_VALID_PIXELS: dict[str, int] = {
    "Lagoa dos Barros":   2000,
    "Lagoa Itapeva":      3000,
    "Lagoa Itapeva":      2000,
    "Lagoa de Tramandaí": 1000,
    "Lagoa do Armazém":   1000,
    "Lagoa do Peixoto":    300,
    "Lagoa Caconde":       100,
}
_MIN_VALID_PIXELS_DEFAULT: int = 200

# Máximo de getInfo() simultâneos ao GEE — limite empírico ~40 por projeto.
# Mantemos em 8 para deixar margem a outros serviços/usuários do mesmo projeto.
_MAX_GEE_CONCURRENT: int = 8

# Lagoas processadas em paralelo. Mais do que 4 raramente ajuda dado o
# semáforo acima e o overhead de contexto do GEE por thread.
_MAX_LAGOA_WORKERS: int = 4

# Timeout em segundos para cada getInfo() — evita travamento indefinido.
# 90 s é generoso para reduceRegion; chamadas simples (date, cloud_pct) terminam em < 5 s.
_GETINFO_TIMEOUT_S: int = 90

# Semáforo global compartilhado entre todas as threads de lagoa.
_gee_semaphore: threading.Semaphore = threading.Semaphore(_MAX_GEE_CONCURRENT)

# Executor compartilhado usado para impor timeout nos getInfo().
# Precisa de workers suficientes para não serializar as chamadas concorrentes.
_timeout_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=_MAX_GEE_CONCURRENT)


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _getinfo_with_retry(ee_obj, retries: int = 4, base_backoff: float = 5.0) -> Any:
    """
    Executa getInfo() com semáforo global, timeout e retry exponencial.

    - Semáforo: no máximo _MAX_GEE_CONCURRENT chamadas simultâneas ao GEE.
    - Timeout: _GETINFO_TIMEOUT_S segundos por chamada — evita travamento indefinido.
    - Retry: erros de quota/rate limit e timeouts aguardam backoff antes de retentar.
    - Outros erros (imagem inválida, 503 permanente) são propagados imediatamente.
    """
    for attempt in range(retries):
        with _gee_semaphore:
            future = _timeout_executor.submit(ee_obj.getInfo)
            try:
                return future.result(timeout=_GETINFO_TIMEOUT_S)
            except FuturesTimeoutError:
                future.cancel()
                wait = base_backoff * (2 ** attempt)
                logger.warning(
                    "GEE timeout após %d s (tentativa %d/%d) — aguardando %.0f s",
                    _GETINFO_TIMEOUT_S, attempt + 1, retries, wait,
                )
                if attempt < retries - 1:
                    time.sleep(wait)
                    continue
                raise TimeoutError(
                    f"GEE não respondeu em {_GETINFO_TIMEOUT_S} s após {retries} tentativas"
                )
            except Exception as exc:
                msg = str(exc).lower()
                is_quota = any(k in msg for k in ("too many", "quota", "rate", "capacity", "503"))
                if is_quota and attempt < retries - 1:
                    wait = base_backoff * (2 ** attempt)
                    logger.warning(
                        "GEE rate limit (tentativa %d/%d) — aguardando %.0f s: %s",
                        attempt + 1, retries, wait, exc,
                    )
                    time.sleep(wait)
                    continue
                raise


def _process_lagoa(
    lagoa_name: str,
    lagoa_cfg: dict,
    s2_base,
    ano_inicio: int,
    ano_fim: int,
    now: datetime,
    force: bool,
) -> dict:
    """
    Processa todas as imagens de uma lagoa em uma thread dedicada.

    Faz 2 getInfo() por imagem (era 7):
      1. ee.Dictionary{date, cloud_pct}  — metadados da cena
      2. reduceRegion combinado          — mean + percentile([10,90]) + count

    O semáforo _gee_semaphore é adquirido dentro de _getinfo_with_retry(),
    garantindo throttling global entre todas as threads em execução.

    Returns:
        {"saved": int, "skipped": int, "errors": list[str]}
    """
    import ee

    geom_raw = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
    buffer_m = lagoa_cfg.get("buffer_negativo_m", 0)
    geom     = geom_raw.buffer(-buffer_m) if buffer_m > 0 else geom_raw
    min_pix  = _MIN_VALID_PIXELS.get(lagoa_name, _MIN_VALID_PIXELS_DEFAULT)

    mes_fim_ultimo = now.month if ano_fim == now.year else 12
    d0 = f"{ano_inicio}-01-01"
    d1 = f"{ano_fim}-{mes_fim_ultimo:02d}-{_last_day(ano_fim, mes_fim_ultimo)}"

    col = s2_base.filterDate(d0, d1).filterBounds(geom_raw)

    n_images = _getinfo_with_retry(col.size())
    if n_images == 0:
        logger.debug("Stats: sem imagens — %s %s..%s", lagoa_name, d0, d1)
        return {"saved": 0, "skipped": 0, "errors": []}

    logger.info(
        "Stats: %s — %d imagens a processar (%s..%s)",
        lagoa_name, n_images, d0, d1,
    )

    # Reducer combinado: 1 chamada GEE entrega mean + percentile + count para todas as bandas.
    # sharedInputs=True aplica cada sub-reducer às mesmas bandas de entrada.
    # Resultados usados: NDCI_mean, NDTI_mean, NDWI_mean, FAI_mean,
    #                    NDCI_p10, NDCI_p90, NDCI_count.
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )

    image_list = col.toList(n_images)
    saved, skipped, errors = 0, 0, []
    _last_aggregated_month: tuple[int, int] | None = None
    _saved_this_month = 0

    db       = SessionLocal()
    img_repo = ImageRecordRepository(db)
    wq_repo  = WaterQualityRepository(db)

    try:
        for i in range(n_images):
            img = ee.Image(image_list.get(i))

            # ── 1º getInfo(): data + cloud_pct juntos ─────────────────────────
            meta = _getinfo_with_retry(
                ee.Dictionary({
                    "date":      img.date().format("YYYY-MM-dd"),
                    "cloud_pct": img.get("CLOUDY_PIXEL_PERCENTAGE"),
                })
            )
            date_str  = meta["date"]
            img_date  = date.fromisoformat(date_str)
            cloud_pct = _safe_float(meta.get("cloud_pct"))

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

                # ── 2º getInfo(): mean + percentile + count em 1 chamada ───────
                stats = _getinfo_with_retry(
                    water_img.select(["NDCI", "NDTI", "NDWI", "FAI"]).reduceRegion(
                        reducer=reducer,
                        geometry=geom,
                        scale=_REDUCE_SCALE_M,
                        maxPixels=_MAX_PIXELS,
                        bestEffort=True,
                    )
                )

                # count() em pixels não-mascarados — equivalente ao sum(mask) anterior
                n_pixels = int(stats.get("NDCI_count") or 0)

                if n_pixels < min_pix:
                    logger.debug(
                        "Stats: descartando %s %s — pixels=%d < min=%d",
                        lagoa_name, date_str, n_pixels, min_pix,
                    )
                    skipped += 1
                    continue

                ndci_mean = _safe_float(stats.get("NDCI_mean"))
                ndti_mean = _safe_float(stats.get("NDTI_mean"))
                ndwi_mean = _safe_float(stats.get("NDWI_mean"))
                fai_mean  = _safe_float(stats.get("FAI_mean"))
                ndci_p10  = _safe_float(stats.get("NDCI_p10"))
                ndci_p90  = _safe_float(stats.get("NDCI_p90"))

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
                _saved_this_month += 1
                logger.info(
                    "Stats: %s %s — ndci=%.4f n_pixels=%d cloud=%.1f%%",
                    lagoa_name, date_str,
                    ndci_mean or 0, n_pixels, cloud_pct or 0,
                )

            except Exception as exc:
                db.rollback()
                msg = f"{lagoa_name}/{date_str}: {exc}"
                errors.append(msg)
                logger.warning("Stats erro: %s", msg)

        # Agrega o último mês da lagoa — só se teve saves nele.
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
        elif saved == 0:
            logger.info("Stats: %s sem novos registros — agregação ignorada", lagoa_name)

    finally:
        db.close()

    return {"saved": saved, "skipped": skipped, "errors": errors}


def _sync_collect_stats(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    force: bool = False,
) -> dict:
    """
    Coleta estatísticas NDCI/NDTI/NDWI por imagem individual via GEE.

    Processa até _MAX_LAGOA_WORKERS lagoas em paralelo via ThreadPoolExecutor.
    O semáforo _gee_semaphore (_MAX_GEE_CONCURRENT slots) limita o total de
    getInfo() simultâneos ao GEE — independente de quantas threads estejam ativas.

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

    # Pipeline base: cloud mask SCL + índices.
    # Objetos ee são lazy (não executam no cliente) — thread-safe para compartilhar.
    s2_base = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _MAX_CLOUD_PCT))
        .map(cloud_mask_s2)
        .map(add_water_indices)
    )

    n_workers = min(_MAX_LAGOA_WORKERS, len(lagoas_cfg))
    logger.info(
        "Stats: iniciando %d lagoas com %d workers paralelos (semáforo GEE=%d)",
        len(lagoas_cfg), n_workers, _MAX_GEE_CONCURRENT,
    )

    saved_total, skipped_total, errors_total = 0, 0, []

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(
                _process_lagoa,
                lagoa_name, lagoa_cfg, s2_base,
                ano_inicio, ano_fim, now, force,
            ): lagoa_name
            for lagoa_name, lagoa_cfg in lagoas_cfg.items()
        }

        for future in as_completed(futures):
            lagoa_name = futures[future]
            try:
                result = future.result()
                saved_total   += result["saved"]
                skipped_total += result["skipped"]
                errors_total.extend(result["errors"])
                logger.info(
                    "Stats: %s concluída — salvos=%d pulados=%d erros=%d",
                    lagoa_name, result["saved"], result["skipped"], len(result["errors"]),
                )
            except Exception as exc:
                msg = f"{lagoa_name}: thread falhou — {exc}"
                errors_total.append(msg)
                logger.error("Stats: %s", msg)

    return {"saved": saved_total, "skipped": skipped_total, "errors": errors_total}


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
