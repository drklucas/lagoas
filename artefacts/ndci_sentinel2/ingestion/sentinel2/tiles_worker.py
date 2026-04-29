"""
Worker: geração de tiles visuais por imagem individual (Sentinel-2, 20 m).

Para cada ImageRecord (data exata de passagem do satélite), gera tiles de
cada índice configurado. Um tile por imagem × lagoa × índice.

Metodologia: Pi & Guasselli (SBSR 2025) — granularidade por imagem individual,
preservando eventos de curta duração (bloom de cianobactérias, etc.).

Pipeline por imagem:
  1. Filtra S2_SR_HARMONIZED para a data exata (filterDate de 1 dia)
  2. Aplica máscara SCL adaptativa (permissiva dentro da lagoa, completa fora)
  3. Calcula NDCI, NDTI, NDWI
  4. Mosaic (combina tiles S2 do mesmo dia que cobrem a lagoa)
  5. Aplica máscara de água (NDWI > -0.5) → pixels de terra ficam transparentes
  6. getMapId() com vis_params → tile_url + map_id → salvo no banco
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from config import ACTIVE_LAGOAS, LAGOAS, SENTINEL2_START_YEAR, TILE_TTL_HOURS
from core.index_registry import INDICES
from ingestion.gee_auth import init_ee, extract_tile_url
from ingestion.sentinel2.cloud_mask import cloud_mask_s2_water
from ingestion.sentinel2.band_math import add_water_indices, water_mask
from storage.database import SessionLocal
from storage.models import ImageRecord
from storage.repositories.map_tiles import MapTileRepository

logger = logging.getLogger(__name__)

# Índices gerados por este worker (apenas domínio 'water')
_WATER_INDICES = [key for key, cfg in INDICES.items() if cfg.domain == "water"]


def _make_cloud_fn(geom):
    """Retorna uma função de máscara SCL adaptativa fechada sobre geom."""
    def _fn(img):
        return cloud_mask_s2_water(img, geom)
    return _fn


def _sync_generate_tiles(
    ano_inicio: int = SENTINEL2_START_YEAR,
    ano_fim: int | None = None,
    lagoas: list[str] | None = None,
    indices: list[str] | None = None,
    force: bool = False,
) -> dict:
    """
    Gera tiles visuais para cada ImageRecord no intervalo de anos especificado.

    Itera sobre os ImageRecords existentes no banco — não repete processamento
    GEE para datas sem dados, e não gera tiles para datas inexistentes.

    Args:
        ano_inicio: primeiro ano a processar (default: 2017)
        ano_fim:    último ano (default: ano atual)
        lagoas:     lagoas a processar (default: todas do config)
        indices:    índice keys a gerar (default: todos os water indices)
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

    db   = SessionLocal()
    repo = MapTileRepository(db)

    try:
        # Busca ImageRecords no intervalo — fonte de verdade das datas disponíveis
        image_records = (
            db.query(ImageRecord)
            .filter(
                ImageRecord.satellite == "sentinel2",
                ImageRecord.lagoa.in_(list(lagoas_cfg.keys())),
                ImageRecord.ano >= ano_inicio,
                ImageRecord.ano <= ano_fim,
            )
            .order_by(ImageRecord.lagoa, ImageRecord.data)
            .all()
        )

        if not image_records:
            return {
                "saved": 0, "skipped": 0,
                "errors": ["Nenhum ImageRecord encontrado. Execute POST /api/workers/collect-stats primeiro."],
            }

        logger.info(
            "generate-tiles: %d imagens × %d índices para processar",
            len(image_records), len(idx_keys),
        )

        # Pré-computa geometrias e coleções por lagoa (uma vez; filtro de data
        # ocorre no loop interno)
        geoms: dict[str, tuple] = {}
        for lagoa_name, lagoa_cfg in lagoas_cfg.items():
            geom_raw = ee.Geometry.Polygon([lagoa_cfg["polygon"]])
            buffer_m = lagoa_cfg.get("buffer_negativo_m", 0)
            geom     = geom_raw.buffer(-buffer_m) if buffer_m > 0 else geom_raw
            s2_lagoa = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .map(_make_cloud_fn(geom))
                .map(add_water_indices)
            )
            geoms[lagoa_name] = (geom_raw, geom, lagoa_cfg["bbox"], s2_lagoa)

        for img_rec in image_records:
            lagoa_name = img_rec.lagoa
            if lagoa_name not in geoms:
                continue
            geom_raw, geom, bounds, s2_lagoa = geoms[lagoa_name]

            for idx_key in idx_keys:
                if idx_key not in INDICES:
                    continue
                idx_cfg = INDICES[idx_key]

                if not force:
                    existing = repo.get(
                        satellite="sentinel2",
                        index_key=idx_key,
                        data=img_rec.data,
                        lagoa=lagoa_name,
                    )
                    if existing and existing.is_valid:
                        skipped += 1
                        continue

                try:
                    d0 = img_rec.data.isoformat()
                    d1 = (img_rec.data + timedelta(days=1)).isoformat()

                    daily = (
                        s2_lagoa
                        .filterDate(d0, d1)
                        .filterBounds(geom_raw)
                    )

                    if daily.size().getInfo() == 0:
                        logger.debug("Tiles: sem imagens — %s %s", lagoa_name, d0)
                        skipped += 1
                        continue

                    # mosaic() combina múltiplos tiles S2 do mesmo dia (diferentes
                    # órbitas ou swaths que cobrem a mesma lagoa)
                    composite = daily.mosaic()
                    water_img = water_mask(composite, threshold=-0.5).clip(geom)

                    band_name = idx_key.upper()   # "NDCI", "NDTI", "NDWI"
                    map_info  = (
                        water_img.select(band_name)
                        .getMapId(idx_cfg.vis_params)
                    )
                    tile_url   = extract_tile_url(map_info)
                    map_id_str = map_info.get("mapid", "")

                    repo.upsert(
                        satellite="sentinel2",
                        index_key=idx_key,
                        data=img_rec.data,
                        lagoa=lagoa_name,
                        tile_url=tile_url,
                        map_id=map_id_str,
                        vis_params=idx_cfg.vis_params,
                        bounds=bounds,
                        ttl_hours=TILE_TTL_HOURS,
                    )
                    saved += 1
                    logger.info(
                        "Tile %s/%s %s — OK",
                        idx_key, lagoa_name, d0,
                    )

                except Exception as exc:
                    db.rollback()
                    msg = f"{idx_key}/{lagoa_name}/{img_rec.data}: {exc}"
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
