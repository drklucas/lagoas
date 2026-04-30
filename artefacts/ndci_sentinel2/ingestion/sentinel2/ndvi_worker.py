"""
Worker: extração de NDVI no anel de vegetação terrestre (Sentinel-2 via GEE).

Geometria de análise: anel anular definido por veg_inner_m e veg_outer_m
no config.py — inicia fora do polígono da lagoa para evitar FAI de borda.

Máscara: NDWI < 0 (retém apenas pixels de terra).
Índice: NDVI = (B8 - B4) / (B8 + B4)

Pipeline por lagoa × imagem:
  1. S2_SR_HARMONIZED filtrado por data e CLOUDY_PIXEL_PERCENTAGE < 20 %
  2. SCL cloud mask (remove sombras e nuvens)
  3. Compute NDWI e NDVI via add_water_indices (já inclui NDVI)
  4. Land mask: NDWI < 0 (exclui água residual no anel)
  5. reduceRegion (mean + percentile + count) no anel
  6. Filtro por MIN_VALID_PIXELS_VEG
  7. Salvo em ndvi_vegetation_records
  8. Agregação mensal atualizada em ndvi_vegetation_monthly
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import date, datetime
from typing import Any

from config import ACTIVE_LAGOAS, LAGOAS, SENTINEL2_START_YEAR
from ingestion.gee_auth import init_ee
from ingestion.sentinel2.cloud_mask import cloud_mask_s2
from ingestion.sentinel2.band_math import add_water_indices, land_mask
from storage.database import SessionLocal
from storage.repositories.ndvi import NdviRepository

logger = logging.getLogger(__name__)

_REDUCE_SCALE_M: int      = 20
_MAX_PIXELS: int          = 1_000_000
_MAX_CLOUD_PCT: float     = 20.0
_MIN_VALID_PIXELS_VEG: int = 50      # anel tem área menor — limiar mais baixo que água
_MAX_GEE_CONCURRENT: int  = 8
_MAX_LAGOA_WORKERS: int   = 4
_GETINFO_TIMEOUT_S: int   = 90

_gee_semaphore: threading.Semaphore     = threading.Semaphore(_MAX_GEE_CONCURRENT)
_timeout_executor: ThreadPoolExecutor   = ThreadPoolExecutor(max_workers=_MAX_GEE_CONCURRENT)


def _safe_float(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _getinfo_with_retry(ee_obj, retries: int = 4, base_backoff: float = 5.0) -> Any:
    for attempt in range(retries):
        with _gee_semaphore:
            future = _timeout_executor.submit(ee_obj.getInfo)
            try:
                return future.result(timeout=_GETINFO_TIMEOUT_S)
            except FuturesTimeoutError:
                future.cancel()
                wait = base_backoff * (2 ** attempt)
                logger.warning("GEE timeout %d s (tentativa %d/%d) — aguardando %.0f s",
                               _GETINFO_TIMEOUT_S, attempt + 1, retries, wait)
                if attempt < retries - 1:
                    time.sleep(wait)
                    continue
                raise TimeoutError(f"GEE não respondeu em {_GETINFO_TIMEOUT_S} s após {retries} tentativas")
            except Exception as exc:
                msg = str(exc).lower()
                is_quota = any(k in msg for k in ("too many", "quota", "rate", "capacity", "503"))
                if is_quota and attempt < retries - 1:
                    wait = base_backoff * (2 ** attempt)
                    logger.warning("GEE rate limit (tentativa %d/%d) — aguardando %.0f s: %s",
                                   attempt + 1, retries, wait, exc)
                    time.sleep(wait)
                    continue
                raise


def _build_veg_ring(geom_raw, veg_inner_m: int, veg_outer_m: int):
    """Anel anular para fora da lagoa: de veg_inner_m a veg_outer_m metros."""
    import ee
    inner = geom_raw.buffer(veg_inner_m)
    outer = geom_raw.buffer(veg_outer_m)
    return outer.difference(inner)


def _process_lagoa(
    lagoa_name: str,
    lagoa_cfg: dict,
    s2_base,
    ano_inicio: int,
    ano_fim: int,
    now: datetime,
    force: bool,
) -> dict:
    import ee

    veg_inner_m = lagoa_cfg.get("veg_inner_m", 100)
    veg_outer_m = lagoa_cfg.get("veg_outer_m", 500)

    if veg_outer_m <= veg_inner_m:
        logger.warning("NDVI: %s — veg_outer_m (%d) ≤ veg_inner_m (%d), pulando",
                       lagoa_name, veg_outer_m, veg_inner_m)
        return {"saved": 0, "skipped": 0, "errors": []}

    geom_raw  = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
    veg_ring  = _build_veg_ring(geom_raw, veg_inner_m, veg_outer_m)

    mes_fim_ultimo = now.month if ano_fim == now.year else 12
    d0 = f"{ano_inicio}-01-01"
    d1 = f"{ano_fim}-{mes_fim_ultimo:02d}-{calendar.monthrange(ano_fim, mes_fim_ultimo)[1]}"

    col = s2_base.filterDate(d0, d1).filterBounds(veg_ring)

    n_images = _getinfo_with_retry(col.size())
    if n_images == 0:
        logger.debug("NDVI: sem imagens — %s %s..%s", lagoa_name, d0, d1)
        return {"saved": 0, "skipped": 0, "errors": []}

    logger.info("NDVI: %s — %d imagens (%s..%s) | anel %d–%d m",
                lagoa_name, n_images, d0, d1, veg_inner_m, veg_outer_m)

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.percentile([10, 90]), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
    )

    image_list  = col.toList(n_images)
    saved, skipped, errors = 0, 0, []
    _last_aggregated_month: tuple[int, int] | None = None
    _saved_this_month = 0

    db   = SessionLocal()
    repo = NdviRepository(db)

    try:
        for i in range(n_images):
            img = ee.Image(image_list.get(i))

            meta = _getinfo_with_retry(
                ee.Dictionary({
                    "date":      img.date().format("YYYY-MM-dd"),
                    "cloud_pct": img.get("CLOUDY_PIXEL_PERCENTAGE"),
                })
            )
            date_str  = meta["date"]
            img_date  = date.fromisoformat(date_str)
            cloud_pct = _safe_float(meta.get("cloud_pct"))

            current_month = (img_date.year, img_date.month)
            if _last_aggregated_month and current_month != _last_aggregated_month:
                if _saved_this_month > 0:
                    _update_monthly(lagoa_name, repo, _last_aggregated_month)
                    logger.info("NDVI: agregação mensal %s %d-%02d concluída",
                                lagoa_name, *_last_aggregated_month)
                _saved_this_month = 0
            _last_aggregated_month = current_month

            if not force and repo.exists("sentinel2", lagoa_name, img_date):
                skipped += 1
                continue

            try:
                land_img = land_mask(img)

                stats = None
                try:
                    stats = _getinfo_with_retry(
                        land_img.select(["NDVI", "NDWI"]).reduceRegion(
                            reducer=reducer,
                            geometry=veg_ring,
                            scale=_REDUCE_SCALE_M,
                            maxPixels=_MAX_PIXELS,
                            bestEffort=True,
                        )
                    )
                except Exception as exc:
                    logger.warning("NDVI: reduceRegion falhou %s %s: %s", lagoa_name, date_str, exc)

                if stats is None:
                    skipped += 1
                    continue

                n_pixels = int(stats.get("NDVI_count") or 0)
                if n_pixels < _MIN_VALID_PIXELS_VEG:
                    logger.debug("NDVI: descartando %s %s — pixels=%d < min=%d",
                                 lagoa_name, date_str, n_pixels, _MIN_VALID_PIXELS_VEG)
                    skipped += 1
                    continue

                repo.upsert_image(
                    satellite="sentinel2",
                    lagoa=lagoa_name,
                    data=img_date,
                    ndvi_mean=_safe_float(stats.get("NDVI_mean")),
                    ndvi_p90 =_safe_float(stats.get("NDVI_p90")),
                    ndvi_p10 =_safe_float(stats.get("NDVI_p10")),
                    n_pixels =n_pixels,
                    cloud_pct=cloud_pct,
                )
                saved += 1
                _saved_this_month += 1
                logger.info("NDVI: %s %s — ndvi=%.4f n_pixels=%d cloud=%.1f%%",
                            lagoa_name, date_str,
                            _safe_float(stats.get("NDVI_mean")) or 0, n_pixels, cloud_pct or 0)

            except Exception as exc:
                db.rollback()
                msg = f"{lagoa_name}/{date_str}: {exc}"
                errors.append(msg)
                logger.warning("NDVI erro: %s", msg)

        if _saved_this_month > 0 and _last_aggregated_month:
            _update_monthly(lagoa_name, repo, _last_aggregated_month)
            logger.info("NDVI: agregação mensal %s %d-%02d concluída",
                        lagoa_name, *_last_aggregated_month)
        elif saved == 0:
            logger.info("NDVI: %s sem novos registros — agregação ignorada", lagoa_name)

    finally:
        db.close()

    return {"saved": saved, "skipped": skipped, "errors": errors}


def _update_monthly(lagoa: str, repo: NdviRepository, month: tuple[int, int]) -> None:
    ano, mes = month
    rows = repo.get_monthly_aggregation(lagoa=lagoa, satellite="sentinel2")
    for row in rows:
        if row["ano"] == ano and row["mes"] == mes:
            try:
                repo.upsert_monthly(
                    satellite="sentinel2",
                    lagoa=lagoa,
                    ano=ano,
                    mes=mes,
                    ndvi_mean=row["ndvi_mean"],
                    ndvi_p90 =row["ndvi_p90"],
                    ndvi_p10 =row["ndvi_p10"],
                    n_pixels =row["n_pixels"],
                )
            except Exception as exc:
                logger.warning("NDVI: falha ao agregar %s %d-%02d: %s", lagoa, ano, mes, exc)
            break


def _sync_collect_ndvi(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    force: bool = False,
) -> dict:
    if not init_ee():
        return {"saved": 0, "skipped": 0, "errors": ["GEE init failed"]}

    import ee

    now     = datetime.utcnow()
    ano_fim = ano_fim or now.year
    allowed = lagoas or ACTIVE_LAGOAS or list(LAGOAS)

    # Só processa lagoas que tenham veg_inner_m e veg_outer_m configurados
    lagoas_cfg = {
        k: v for k, v in LAGOAS.items()
        if k in allowed and "veg_inner_m" in v and "veg_outer_m" in v
    }

    if not lagoas_cfg:
        return {"saved": 0, "skipped": 0, "errors": ["Nenhuma lagoa com veg_inner_m/veg_outer_m configurados"]}

    s2_base = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _MAX_CLOUD_PCT))
        .map(cloud_mask_s2)
        .map(add_water_indices)
    )

    n_workers = min(_MAX_LAGOA_WORKERS, len(lagoas_cfg))
    logger.info("NDVI: iniciando %d lagoas com %d workers (semáforo GEE=%d)",
                len(lagoas_cfg), n_workers, _MAX_GEE_CONCURRENT)

    saved_total, skipped_total, errors_total = 0, 0, []

    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(_process_lagoa, name, cfg, s2_base, ano_inicio, ano_fim, now, force): name
            for name, cfg in lagoas_cfg.items()
        }
        for future in as_completed(futures):
            lagoa_name = futures[future]
            try:
                result = future.result()
                saved_total   += result["saved"]
                skipped_total += result["skipped"]
                errors_total.extend(result["errors"])
                logger.info("NDVI: %s concluída — salvos=%d pulados=%d erros=%d",
                            lagoa_name, result["saved"], result["skipped"], len(result["errors"]))
            except Exception as exc:
                msg = f"{lagoa_name}: thread falhou — {exc}"
                errors_total.append(msg)
                logger.error("NDVI: %s", msg)

    return {"saved": saved_total, "skipped": skipped_total, "errors": errors_total}


async def collect_ndvi(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    force: bool = False,
) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _sync_collect_ndvi(ano_inicio, ano_fim, lagoas, force),
    )
