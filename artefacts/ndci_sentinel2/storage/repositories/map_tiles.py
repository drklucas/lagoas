"""
Repositório para MapTileRecord — CRUD e cache de map_id.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

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
        ano: int,
        mes: int,
        lagoa: str,
        tile_url: str,
        map_id: str,
        vis_params: dict,
        bounds: list[float],
        ttl_hours: int = 23,
    ) -> MapTileRecord:
        """Insere ou atualiza um tile. Invalida o cache em memória."""
        now = datetime.utcnow()
        expires = now + timedelta(hours=ttl_hours)

        rec = (
            self._db.query(MapTileRecord)
            .filter_by(
                satellite=satellite,
                index_key=index_key,
                ano=ano,
                mes=mes,
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
                ano=ano,
                mes=mes,
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
        ano: int,
        mes: int,
        lagoa: str,
    ) -> MapTileRecord | None:
        return (
            self._db.query(MapTileRecord)
            .filter_by(
                satellite=satellite,
                index_key=index_key,
                ano=ano,
                mes=mes,
                lagoa=lagoa,
            )
            .first()
        )

    def get_map_id_for_key(self, tile_key: str) -> str | None:
        """
        Resolve tile_key → map_id, usando cache em memória primeiro.
        tile_key formato: "<satellite>|<index_key>|<ano>|<mes>|<lagoa>"
        """
        cached = _cache_get(tile_key)
        if cached:
            return cached

        parts = tile_key.split("|", 4)
        if len(parts) != 5:
            return None
        satellite, index_key, ano_s, mes_s, lagoa = parts

        try:
            ano = int(ano_s)
            mes = int(mes_s)
        except ValueError:
            return None

        rec = self.get(
            satellite=satellite,
            index_key=index_key,
            ano=ano,
            mes=mes,
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
          - períodos mensais disponíveis (YYYY-MM)
          - contagem de tiles válidos vs expirados
        """
        now = datetime.utcnow()
        rows = self._db.query(MapTileRecord).all()
        result: dict[str, dict] = {}

        for r in rows:
            key = r.index_key
            if key not in result:
                result[key] = {
                    "lagoas":           set(),
                    "periodos_mensais": set(),
                    "total_tiles":      0,
                    "tiles_validos":    0,
                    "tiles_expirados":  0,
                }
            g = result[key]
            g["lagoas"].add(r.lagoa)
            g["periodos_mensais"].add(f"{r.ano}-{r.mes:02d}")
            g["total_tiles"] += 1
            if r.expires_at and r.expires_at > now:
                g["tiles_validos"] += 1
            else:
                g["tiles_expirados"] += 1

        # Serializa sets para listas ordenadas
        for v in result.values():
            v["lagoas"]           = sorted(v["lagoas"])
            v["periodos_mensais"] = sorted(v["periodos_mensais"])

        return result

    def invalidate_cache(self, tile_key: str | None = None) -> None:
        """Invalida o cache em memória — chamado após refresh de tiles."""
        _cache_invalidate(tile_key)
