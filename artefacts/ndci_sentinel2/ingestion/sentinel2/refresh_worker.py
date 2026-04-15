"""
Worker: refresh de tiles GEE prestes a expirar.

Os Map IDs do GEE expiram ~24 h após a geração.
Este worker deve ser agendado a cada 12 h para regenerar tiles
cujo expires_at cai dentro das próximas `window_hours` horas (default: 6 h).

Fluxo:
  1. Busca na tabela ndci_map_tiles todos os tiles com expires_at <= now + window
  2. Para cada tile, reconstrói a imagem GEE com filterDate(data, data+1d)
  3. Chama getMapId() novamente → novo map_id + tile_url
  4. Atualiza o registro no banco e invalida o cache de map_id
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from config import LAGOAS, TILE_TTL_HOURS, TILE_REFRESH_WINDOW_HOURS
from core.index_registry import INDICES
from ingestion.gee_auth import init_ee, extract_tile_url
from ingestion.sentinel2.cloud_mask import cloud_mask_s2
from ingestion.sentinel2.band_math import add_water_indices, water_mask
from storage.database import SessionLocal
from storage.models import MapTileRecord
from storage.repositories.map_tiles import MapTileRepository

logger = logging.getLogger(__name__)


def _rebuild_image(rec: MapTileRecord):
    """
    Reconstrói o objeto ee.Image para um tile existente usando filterDate de 1 dia.
    Retorna None se não houver imagens disponíveis para a data.
    """
    import ee

    if rec.satellite != "sentinel2":
        logger.warning("Refresh: satélite '%s' não suportado neste worker.", rec.satellite)
        return None

    if not rec.data:
        logger.warning("Refresh: tile %s sem data — pulando.", rec.tile_key)
        return None

    lagoa_cfg = LAGOAS.get(rec.lagoa)
    if not lagoa_cfg:
        logger.warning("Refresh: lagoa '%s' não encontrada no config.", rec.lagoa)
        return None

    d0 = rec.data.isoformat()
    d1 = (rec.data + timedelta(days=1)).isoformat()

    geom_raw = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
    buffer_m = lagoa_cfg.get("buffer_negativo_m", 0)
    geom     = geom_raw.buffer(-buffer_m) if buffer_m > 0 else geom_raw

    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterDate(d0, d1)
        .filterBounds(geom_raw)
        .map(cloud_mask_s2)
        .map(add_water_indices)
    )

    if col.size().getInfo() == 0:
        return None

    composite = col.mosaic()
    water_img = water_mask(composite).clip(geom)

    band_name = rec.index_key.upper()
    return water_img.select(band_name)


def _sync_refresh_expiring(window_hours: int = TILE_REFRESH_WINDOW_HOURS) -> dict:
    """
    Regenera tiles que expiram dentro das próximas `window_hours` horas.

    Returns:
        {"refreshed": int, "skipped": int, "errors": list[str]}
    """
    if not init_ee():
        return {"refreshed": 0, "skipped": 0, "errors": ["GEE init failed"]}

    db   = SessionLocal()
    repo = MapTileRepository(db)

    refreshed, skipped, errors = 0, 0, []

    try:
        expiring = repo.get_expiring_tiles(window_hours=window_hours)

        if not expiring:
            logger.info("Refresh: nenhum tile expirando em <%dh.", window_hours)
            return {"refreshed": 0, "skipped": 0, "errors": []}

        logger.info(
            "Refresh: %d tiles expirando em <%dh — regenerando.",
            len(expiring), window_hours,
        )

        for rec in expiring:
            try:
                image = _rebuild_image(rec)
                if image is None:
                    logger.debug(
                        "Refresh: sem imagens para %s/%s %s — pulando.",
                        rec.index_key, rec.lagoa, rec.data,
                    )
                    skipped += 1
                    continue

                idx_cfg   = INDICES.get(rec.index_key)
                vis_params = idx_cfg.vis_params if idx_cfg else {
                    "min": rec.vis_min,
                    "max": rec.vis_max,
                    "palette": rec.palette or [],
                }

                map_info = image.getMapId(vis_params)
                bounds   = LAGOAS[rec.lagoa]["bbox"]

                repo.upsert(
                    satellite=rec.satellite,
                    index_key=rec.index_key,
                    data=rec.data,
                    lagoa=rec.lagoa,
                    tile_url=extract_tile_url(map_info),
                    map_id=map_info.get("mapid", ""),
                    vis_params=vis_params,
                    bounds=bounds,
                    ttl_hours=TILE_TTL_HOURS,
                )
                refreshed += 1
                logger.debug(
                    "Refreshed: %s/%s %s",
                    rec.index_key, rec.lagoa, rec.data,
                )

            except Exception as exc:
                db.rollback()
                msg = f"Refresh {rec.index_key}/{rec.lagoa}/{rec.data}: {exc}"
                errors.append(msg)
                logger.warning(msg)

    finally:
        db.close()

    return {"refreshed": refreshed, "skipped": skipped, "errors": errors}


# ── Wrapper async ─────────────────────────────────────────────────────────────

async def refresh_expiring_tiles(window_hours: int = TILE_REFRESH_WINDOW_HOURS) -> dict:
    """Wrapper async para _sync_refresh_expiring."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _sync_refresh_expiring(window_hours),
    )
