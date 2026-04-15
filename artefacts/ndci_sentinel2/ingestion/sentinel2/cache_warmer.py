"""
Worker: pré-aquecimento do cache em disco de tiles.

Para cada tile registrado no banco (tile_key + bounds + map_id), calcula as
coordenadas XYZ para os zoom levels solicitados e baixa as imagens PNG
diretamente do GEE em paralelo, salvando em disco.

Tiles já em disco são ignorados (idempotente).
O token OAuth é resolvido uma única vez e reutilizado em todo o batch.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

from ingestion.gee_auth import get_oauth_credentials
from storage.database import SessionLocal
from storage.models import MapTileRecord
from storage.tile_disk_cache import DISK_CACHE_ROOT, disk_path, tiles_for_bbox, write_disk

logger = logging.getLogger(__name__)

# Zoom levels padrão — cobre a faixa usada pelo frontend (10–14)
DEFAULT_ZOOM_MIN = 10
DEFAULT_ZOOM_MAX = 14

# Concorrência padrão: suficiente para saturar a banda sem bater nos rate limits do GEE
DEFAULT_CONCURRENCY = 12


async def _fetch_tile(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    map_id: str,
    token: str,
    z: int, x: int, y: int,
    tile_key: str,
) -> str:
    """
    Baixa um único tile do GEE e salva em disco.
    Retorna: "hit" | "saved" | "empty" | "error:<motivo>"
    """
    dp = disk_path(tile_key, z, x, y)
    if dp is None:
        return "skip:no_cache_dir"
    if dp.exists():
        return "hit"

    url = f"https://earthengine.googleapis.com/v1/{map_id}/tiles/{z}/{x}/{y}"
    async with sem:
        try:
            r = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=True,
                timeout=20,
            )
        except Exception as exc:
            return f"error:{exc}"

    if r.status_code == 200:
        ct = r.headers.get("content-type", "")
        if "image" not in ct:
            return "empty"
        # Tiles transparentes (apenas canal alpha, sem dados) ainda são válidos —
        # salvar evita refetch; o frontend simplesmente não exibe nada nessas células.
        write_disk(dp, r.content)
        return "saved"

    if r.status_code == 204:
        return "empty"

    return f"error:http_{r.status_code}"


async def warm_cache(
    zoom_min: int = DEFAULT_ZOOM_MIN,
    zoom_max: int = DEFAULT_ZOOM_MAX,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict:
    """
    Baixa e cacheia em disco todos os tiles dos registros válidos no banco.

    Args:
        zoom_min:    zoom mínimo a cobrir (default 10)
        zoom_max:    zoom máximo a cobrir (default 14)
        concurrency: máximo de downloads simultâneos (default 12)

    Returns:
        {"hit": int, "saved": int, "empty": int, "errors": int, "skipped": int,
         "total": int, "elapsed_s": float}
    """
    if DISK_CACHE_ROOT is None:
        return {"error": "TILE_DISK_CACHE_DIR não configurado — cache em disco desativado."}

    t0 = datetime.utcnow()

    # ── Busca todos os tile records válidos com map_id ─────────────────────────
    db = SessionLocal()
    try:
        records: list[MapTileRecord] = (
            db.query(MapTileRecord)
            .filter(MapTileRecord.map_id.isnot(None))
            .filter(MapTileRecord.map_id != "")
            .all()
        )
        # Serializa o que precisa antes de fechar a sessão
        jobs = [
            {
                "tile_key": r.tile_key,
                "map_id":   r.map_id,
                "bounds":   r.bounds,
            }
            for r in records
            if r.map_id and r.bounds
        ]
    finally:
        db.close()

    if not jobs:
        return {"error": "Nenhum tile com map_id encontrado. Execute generate-tiles primeiro."}

    logger.info(
        "warm-cache: %d tile records × zooms %d–%d × concorrência %d",
        len(jobs), zoom_min, zoom_max, concurrency,
    )

    # ── Token OAuth (resolvido uma vez para todo o batch) ──────────────────────
    creds = get_oauth_credentials()
    if creds is None:
        return {"error": "Credenciais GEE indisponíveis."}
    token = creds.token

    # ── Monta lista de tasks (tile_key, map_id, z, x, y) ──────────────────────
    tasks: list[tuple[str, str, int, int, int]] = []
    skipped_no_bounds = 0

    for job in jobs:
        bounds = job["bounds"]
        if not bounds or len(bounds) != 4:
            skipped_no_bounds += 1
            continue
        for z in range(zoom_min, zoom_max + 1):
            for (tz, tx, ty) in tiles_for_bbox(bounds, z):
                tasks.append((job["tile_key"], job["map_id"], tz, tx, ty))

    total = len(tasks)
    logger.info("warm-cache: %d tiles a processar (+ %d sem bounds)", total, skipped_no_bounds)

    # ── Download paralelo ──────────────────────────────────────────────────────
    counters = {"hit": 0, "saved": 0, "empty": 0, "errors": 0}
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:
        coros = [
            _fetch_tile(client, sem, map_id, token, z, x, y, tile_key)
            for tile_key, map_id, z, x, y in tasks
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

    for res in results:
        if isinstance(res, Exception):
            counters["errors"] += 1
        elif res == "hit":
            counters["hit"] += 1
        elif res == "saved":
            counters["saved"] += 1
        elif res == "empty":
            counters["empty"] += 1
        else:
            counters["errors"] += 1

    elapsed = (datetime.utcnow() - t0).total_seconds()
    logger.info(
        "warm-cache concluído em %.1fs — hit=%d saved=%d empty=%d errors=%d",
        elapsed, counters["hit"], counters["saved"], counters["empty"], counters["errors"],
    )

    return {
        **counters,
        "skipped": skipped_no_bounds,
        "total":   total,
        "elapsed_s": round(elapsed, 1),
    }
