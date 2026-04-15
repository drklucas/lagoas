"""
Cache em disco para tiles PNG do GEE.

Módulo compartilhado entre o proxy (tiles.py) e o warm-cache worker.
A estrutura de diretório é:
  {TILE_DISK_CACHE_DIR}/{satellite}/{index_key}/{ano}/{mes}/{lagoa_slug}/{z}/{x}/{y}.png
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path

from config import TILE_DISK_CACHE_DIR

logger = logging.getLogger(__name__)

# ── Raiz do cache ──────────────────────────────────────────────────────────────

DISK_CACHE_ROOT: Path | None = Path(TILE_DISK_CACHE_DIR) if TILE_DISK_CACHE_DIR else None

if DISK_CACHE_ROOT:
    DISK_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info("Tile disk cache ativo em: %s", DISK_CACHE_ROOT.resolve())


# ── Helpers de caminho ─────────────────────────────────────────────────────────

def _safe_key(tile_key: str) -> str:
    """Converte tile_key em subdiretório seguro para o filesystem.

    "sentinel2|ndci|2023|8|Lagoa do Peixoto" → "sentinel2/ndci/2023/8/lagoa_do_peixoto"
    """
    parts = tile_key.split("|")
    return "/".join(re.sub(r"[^\w\-.]", "_", p).lower() for p in parts)


def disk_path(tile_key: str, z: int, x: int, y: int) -> Path | None:
    """Retorna o caminho no disco para um tile específico, ou None se cache desativado."""
    if DISK_CACHE_ROOT is None:
        return None
    return DISK_CACHE_ROOT / _safe_key(tile_key) / str(z) / str(x) / f"{y}.png"


# ── I/O ────────────────────────────────────────────────────────────────────────

def read_disk(path: Path) -> bytes | None:
    """Lê tile do disco. Retorna None se não existir."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def write_disk(path: Path, data: bytes) -> None:
    """Salva tile no disco, criando diretórios se necessário. Silencia erros."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except Exception as exc:
        logger.warning("Tile disk cache: erro ao salvar %s — %s", path, exc)


# ── Geometria de tiles (Slippy Map) ──────────────────────────────────────────

def _lon_lat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    """Converte (lon, lat) em coordenadas de tile (x, y) no nível de zoom z."""
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    # Clamp defensivo
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def tiles_for_bbox(bbox: list[float], z: int) -> list[tuple[int, int, int]]:
    """Retorna todos os tiles (z, x, y) que cobrem o bbox [west, south, east, north]."""
    west, south, east, north = bbox
    x_min, y_max = _lon_lat_to_tile(west, south, z)
    x_max, y_min = _lon_lat_to_tile(east, north, z)
    return [
        (z, x, y)
        for x in range(x_min, x_max + 1)
        for y in range(y_min, y_max + 1)
    ]
