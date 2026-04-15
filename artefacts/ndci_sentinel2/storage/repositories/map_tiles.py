"""
Repositório para MapTileRecord — CRUD e cache de map_id.

tile_key format: "<satellite>|<index_key>|<YYYY-MM-DD>|<lagoa>"
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from storage.models import MapTileRecord

# ── Cache em memória: tile_key → (map_id, expires_at) ────────────────────────
# Evita hit no banco por request de tile (hot path do proxy).
_cache: dict[str, tuple[str, datetime]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> str | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry[1] > datetime.utcnow():
            return entry[0]
    return None


def _cache_set(key: str, map_id: str, expires_at: datetime) -> None:
    with _cache_lock:
        _cache[key] = (map_id, expires_at)


def _cache_invalidate(key: str | None = None) -> None:
    with _cache_lock:
        if key:
            _cache.pop(key, None)
        else:
            _cache.clear()


class MapTileRepository:
    """Acesso à tabela ndci_map_tiles."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Escrita ───────────────────────────────────────────────────────────────

    def upsert(
        self,
        *,
        satellite: str,
        index_key: str,
        data: date,
        lagoa: str,
        tile_url: str,
        map_id: str,
        vis_params: dict,
        bounds: list[float],
        ttl_hours: int = 23,
    ) -> MapTileRecord:
        """Insere ou atualiza um tile por data de imagem. Invalida o cache em memória."""
        now = datetime.utcnow()
        expires = now + timedelta(hours=ttl_hours)

        rec = (
            self._db.query(MapTileRecord)
            .filter_by(
                satellite=satellite,
                index_key=index_key,
                data=data,
                lagoa=lagoa,
            )
            .first()
        )

        if rec:
            rec.tile_url     = tile_url
            rec.map_id       = map_id
            rec.vis_min      = vis_params.get("min")
            rec.vis_max      = vis_params.get("max")
            rec.palette      = vis_params.get("palette")
            rec.bounds       = bounds
            rec.generated_at = now
            rec.expires_at   = expires
        else:
            rec = MapTileRecord(
                satellite=satellite,
                index_key=index_key,
                data=data,
                ano=data.year,
                mes=data.month,
                lagoa=lagoa,
                tile_url=tile_url,
                map_id=map_id,
                vis_min=vis_params.get("min"),
                vis_max=vis_params.get("max"),
                palette=vis_params.get("palette"),
                bounds=bounds,
                generated_at=now,
                expires_at=expires,
            )
            self._db.add(rec)

        self._db.commit()
        _cache_invalidate(rec.tile_key)
        _cache_set(rec.tile_key, map_id, expires)
        return rec

    # ── Leitura ───────────────────────────────────────────────────────────────

    def get(
        self,
        *,
        satellite: str,
        index_key: str,
        data: date,
        lagoa: str,
    ) -> MapTileRecord | None:
        return (
            self._db.query(MapTileRecord)
            .filter_by(
                satellite=satellite,
                index_key=index_key,
                data=data,
                lagoa=lagoa,
            )
            .first()
        )

    def get_map_id_for_key(self, tile_key: str) -> str | None:
        """
        Resolve tile_key → map_id, usando cache em memória primeiro.
        tile_key formato: "<satellite>|<index_key>|<YYYY-MM-DD>|<lagoa>"
        """
        cached = _cache_get(tile_key)
        if cached:
            return cached

        # maxsplit=3 garante que lagoas com '|' no nome (improvável mas seguro)
        parts = tile_key.split("|", 3)
        if len(parts) != 4:
            return None
        satellite, index_key, date_str, lagoa = parts

        try:
            data_parsed = date.fromisoformat(date_str)
        except ValueError:
            return None

        rec = self.get(
            satellite=satellite,
            index_key=index_key,
            data=data_parsed,
            lagoa=lagoa,
        )
        if not rec or not rec.map_id:
            return None

        expires = rec.expires_at or datetime.utcnow()
        _cache_set(tile_key, rec.map_id, expires)
        return rec.map_id

    def get_expiring_tiles(self, window_hours: int = 6) -> list[MapTileRecord]:
        """Retorna tiles que expiram nas próximas `window_hours` horas."""
        limite = datetime.utcnow() + timedelta(hours=window_hours)
        return (
            self._db.query(MapTileRecord)
            .filter(MapTileRecord.expires_at <= limite)
            .all()
        )

    def get_availability(self) -> dict:
        """
        Resumo de cobertura por índice:
          - lagoas disponíveis
          - datas_por_lagoa: dict lagoa → lista de "YYYY-MM-DD" ordenada
          - contagem de tiles válidos vs expirados
        """
        now = datetime.utcnow()
        rows = self._db.query(MapTileRecord).all()
        result: dict[str, dict] = {}

        for r in rows:
            key = r.index_key
            if key not in result:
                result[key] = {
                    "lagoas":          set(),
                    "datas_por_lagoa": {},
                    "total_tiles":     0,
                    "tiles_validos":   0,
                    "tiles_expirados": 0,
                }
            g = result[key]
            data_str = r.data.isoformat() if r.data else None
            g["lagoas"].add(r.lagoa)
            if data_str:
                g["datas_por_lagoa"].setdefault(r.lagoa, set()).add(data_str)
            g["total_tiles"] += 1
            if r.expires_at and r.expires_at > now:
                g["tiles_validos"] += 1
            else:
                g["tiles_expirados"] += 1

        # Serializa sets para listas ordenadas
        for v in result.values():
            v["lagoas"] = sorted(v["lagoas"])
            v["datas_por_lagoa"] = {
                lagoa: sorted(datas)
                for lagoa, datas in v["datas_por_lagoa"].items()
            }

        return result

    def invalidate_cache(self, tile_key: str | None = None) -> None:
        """Invalida o cache em memória — chamado após refresh de tiles."""
        _cache_invalidate(tile_key)
