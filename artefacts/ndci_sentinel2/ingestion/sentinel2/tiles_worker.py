"""
Worker: geração de tiles visuais NDCI/NDTI para lagoas (Sentinel-2, 20 m).

Por lagoa × mês são gerados tiles de cada índice configurado.
Os tiles são salvos na tabela ndci_map_tiles com TTL de 23 h.

Pipeline por período:
  1. Filtra S2_SR_HARMONIZED por data e geometria da lagoa
  2. Aplica máscara SCL (remove nuvens)
  3. Calcula NDCI, NDTI, NDWI por imagem
  4. Mediana mensal (robusta a nuvens residuais)
  5. Aplica máscara de água (NDWI > -0.1) → pixels de terra ficam transparentes
  6. getMapId() com vis_params → tile_url + map_id → salvo no banco
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import datetime

from config import ACTIVE_LAGOAS, LAGOAS, SENTINEL2_START_YEAR, TILE_TTL_HOURS
from core.index_registry import INDICES
from ingestion.gee_auth import init_ee, extract_tile_url
from ingestion.sentinel2.cloud_mask import cloud_mask_s2
from ingestion.sentinel2.band_math import add_water_indices, water_mask
from storage.database import SessionLocal
from storage.repositories.map_tiles import MapTileRepository

logger = logging.getLogger(__name__)

# Índices gerados por este worker (apenas domínio 'water')
_WATER_INDICES = [key for key, cfg in INDICES.items() if cfg.domain == "water"]


def _sync_generate_tiles(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    indices: list[str] | None = None,
    force: bool = False,
) -> dict:
    """
    Gera tiles visuais para as lagoas e índices especificados.

    Args:
        ano_inicio: primeiro ano a processar (default: 2017)
        ano_fim:    último ano (default: ano atual)
        lagoas:     lista de lagoas a processar (default: todas do config)
        indices:    lista de índice keys a gerar (default: todos os water indices)
        force:      se True, regenera mesmo tiles ainda válidos

    Returns:
        {"saved": int, "skipped": int, "errors": list[str]}
    """
    if not init_ee():
        return {"saved": 0, "skipped": 0, "errors": ["GEE init failed — verifique GEE_SERVICE_ACCOUNT_KEY"]}

    import ee

    now        = datetime.utcnow()
    ano_fim    = ano_fim or now.year
    allowed    = lagoas or ACTIVE_LAGOAS or list(LAGOAS)
    lagoas_cfg = {k: v for k, v in LAGOAS.items() if k in allowed}
    idx_keys   = indices or _WATER_INDICES

    saved, skipped, errors = 0, 0, []

    # Pré-processa: pipeline base da coleção Sentinel-2
    s2_base = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .map(cloud_mask_s2)
        .map(add_water_indices)
    )

    db   = SessionLocal()
    repo = MapTileRepository(db)

    try:
        for lagoa_name, lagoa_cfg in lagoas_cfg.items():
            geom_raw  = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
            buffer_m  = lagoa_cfg.get("buffer_negativo_m", 0)
            geom      = geom_raw.buffer(-buffer_m) if buffer_m > 0 else geom_raw
            bounds    = lagoa_cfg["bbox"]

            for year in range(ano_inicio, ano_fim + 1):
                mes_fim = now.month if year == now.year else 12

                for mes in range(1, mes_fim + 1):
                    for idx_key in idx_keys:
                        if idx_key not in INDICES:
                            continue
                        idx_cfg = INDICES[idx_key]

                        if not force:
                            existing = repo.get(
                                satellite="sentinel2",
                                index_key=idx_key,
                                ano=year,
                                mes=mes,
                                lagoa=lagoa_name,
                            )
                            if existing and existing.is_valid:
                                skipped += 1
                                continue

                        try:
                            ultimo = calendar.monthrange(year, mes)[1]
                            d0 = f"{year}-{mes:02d}-01"
                            d1 = f"{year}-{mes:02d}-{ultimo}"

                            monthly = (
                                s2_base
                                .filterDate(d0, d1)
                                .filterBounds(geom_raw)   # filtro no polígono completo
                            )

                            if monthly.size().getInfo() == 0:
                                logger.debug(
                                    "Tiles: sem imagens — %s %d-%02d",
                                    lagoa_name, year, mes,
                                )
                                skipped += 1
                                continue

                            composite = monthly.median()
                            water_img = water_mask(composite).clip(geom)  # recorte na geom erodida

                            # Seleciona banda do índice pelo nome GEE
                            band_name = idx_key.upper()   # "NDCI" ou "NDTI"
                            map_info  = (
                                water_img.select(band_name)
                                .getMapId(idx_cfg.vis_params)
                            )
                            tile_url   = extract_tile_url(map_info)
                            map_id_str = map_info.get("mapid", "")

                            repo.upsert(
                                satellite="sentinel2",
                                index_key=idx_key,
                                ano=year,
                                mes=mes,
                                lagoa=lagoa_name,
                                tile_url=tile_url,
                                map_id=map_id_str,
                                vis_params=idx_cfg.vis_params,
                                bounds=bounds,
                                ttl_hours=TILE_TTL_HOURS,
                            )
                            saved += 1
                            logger.info(
                                "Tile %s/%s: %s %d-%02d — OK",
                                idx_key, lagoa_name, lagoa_name, year, mes,
                            )

                        except Exception as exc:
                            db.rollback()
                            msg = f"{idx_key}/{lagoa_name}/{year}-{mes:02d}: {exc}"
                            errors.append(msg)
                            logger.warning("Tile erro: %s", msg)

    finally:
        db.close()

    return {"saved": saved, "skipped": skipped, "errors": errors}


# ── Wrapper async ─────────────────────────────────────────────────────────────

async def generate_tiles(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    indices: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Wrapper async para _sync_generate_tiles (roda em executor de thread)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _sync_generate_tiles(ano_inicio, ano_fim, lagoas, indices, force),
    )
