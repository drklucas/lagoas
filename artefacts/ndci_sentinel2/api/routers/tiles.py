"""
Router: /api/tiles — tile URLs XYZ e proxy autenticado para o GEE.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as date_type
from urllib.parse import quote, unquote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from config import LAGOAS
from storage.database import SessionLocal, get_db
from storage.repositories.map_tiles import MapTileRepository
from storage.tile_disk_cache import disk_path, read_disk, write_disk
from ingestion.gee_auth import get_oauth_credentials

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tiles", tags=["Tiles"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tile_to_dict(rec) -> dict:
    """
    Serializa um MapTileRecord para resposta da API.
    A tile_url retornada aponta para o proxy interno — estável mesmo após refresh.
    """
    tile_key  = quote(rec.tile_key, safe="")
    proxy_url = f"/api/tiles/proxy/{{z}}/{{x}}/{{y}}?k={tile_key}"

    return {
        "satellite":    rec.satellite,
        "index_key":    rec.index_key,
        "lagoa":        rec.lagoa,
        "data":         rec.data.isoformat() if rec.data else None,
        "tile_url":     proxy_url,
        "vis_min":      rec.vis_min,
        "vis_max":      rec.vis_max,
        "palette":      rec.palette,
        "bounds":       rec.bounds,
        "generated_at": rec.generated_at.isoformat() if rec.generated_at else None,
        "expires_at":   rec.expires_at.isoformat()   if rec.expires_at   else None,
        "valid":        rec.is_valid,
    }


# ── Proxy autenticado ─────────────────────────────────────────────────────────

@router.get("/proxy/{z}/{x}/{y}")
async def proxy_gee_tile(
    z: int,
    x: int,
    y: int,
    k: str = Query(..., description="tile_key: satellite|index_key|ano|mes|lagoa (URL-encoded)"),
):
    """
    Proxy autenticado para tiles do Google Earth Engine.

    O frontend nunca expõe credenciais GEE — toda requisição passa por aqui.
    Usa cache em memória (tile_key → map_id) para evitar hit no banco por request.
    Quando TILE_DISK_CACHE_DIR está configurado, serve tiles do disco sem ir ao GEE.
    """
    loop = asyncio.get_event_loop()
    key  = unquote(k)

    # ── 1. Cache em disco (hit imediato, sem GEE) ─────────────────────────────
    dp = disk_path(key, z, x, y)
    if dp is not None:
        cached = await loop.run_in_executor(None, read_disk, dp)
        if cached is not None:
            return Response(content=cached, media_type="image/png")

    # ── 2. Resolve map_id (memória → banco) ──────────────────────────────────
    db   = SessionLocal()
    repo = MapTileRepository(db)

    try:
        map_id = await loop.run_in_executor(None, repo.get_map_id_for_key, key)
    finally:
        db.close()

    if not map_id:
        raise HTTPException(404, "Tile não encontrado. Execute o worker de geração.")

    # ── 3. Fetch GEE ──────────────────────────────────────────────────────────
    creds = await loop.run_in_executor(None, get_oauth_credentials)
    if creds is None:
        raise HTTPException(503, "Credenciais GEE indisponíveis.")

    gee_url = f"https://earthengine.googleapis.com/v1/{map_id}/tiles/{z}/{x}/{y}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                gee_url,
                headers={"Authorization": f"Bearer {creds.token}"},
                follow_redirects=True,
            )
        if r.status_code == 200:
            content = r.content
            media   = r.headers.get("content-type", "image/png")
            # ── 4. Persiste no disco para próximas requisições ────────────────
            if dp is not None and "image" in media:
                await loop.run_in_executor(None, write_disk, dp, content)
            return Response(content=content, media_type=media)
        # Map ID expirou — invalida cache para forçar releitura do banco no próximo request
        if r.status_code in (401, 404):
            db2 = SessionLocal()
            MapTileRepository(db2).invalidate_cache(key)
            db2.close()
        raise HTTPException(r.status_code, f"GEE retornou HTTP {r.status_code}")
    except httpx.TimeoutException:
        raise HTTPException(504, "Timeout ao buscar tile do GEE.")


# ── Endpoints de tile ─────────────────────────────────────────────────────────

@router.get("/lagoa/{index_key}")
def get_tile_lagoa(
    index_key: str,
    lagoa: str = Query(..., description="Nome da lagoa (ex: 'Lagoa do Peixoto')"),
    data:  str = Query(..., description="Data da imagem: YYYY-MM-DD"),
    satellite: str = Query("sentinel2"),
    db: Session = Depends(get_db),
):
    """
    Retorna a tile_url para um índice/lagoa/data específicos.

    Exemplo:
      GET /api/tiles/lagoa/ndci?lagoa=Lagoa+do+Peixoto&data=2023-08-07
    """
    try:
        data_parsed = date_type.fromisoformat(data)
    except ValueError:
        raise HTTPException(400, f"Formato de data inválido: '{data}'. Use YYYY-MM-DD.")

    repo = MapTileRepository(db)
    rec  = repo.get(
        satellite=satellite,
        index_key=index_key,
        data=data_parsed,
        lagoa=lagoa,
    )
    if not rec:
        raise HTTPException(
            404,
            f"Tile {index_key}/{lagoa}/{data} não encontrado. "
            f"Execute POST /api/workers/generate-tiles para gerá-lo.",
        )
    return _tile_to_dict(rec)


# ── Endpoints de metadados ─────────────────────────────────────────────────────

@router.get("/lagoas")
def list_lagoas():
    """Lista de lagoas configuradas com bounding boxes."""
    return {
        name: {"bounds": cfg["bbox"]}
        for name, cfg in LAGOAS.items()
    }


@router.get("/availability")
def tile_availability(db: Session = Depends(get_db)):
    """
    Resumo de cobertura por índice:
      - lagoas disponíveis
      - períodos mensais (YYYY-MM)
      - tiles válidos vs expirados
    """
    repo = MapTileRepository(db)
    return repo.get_availability()
