"""
Repositório para GeoRegion — regiões geográficas desenhadas no frontend.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from storage.models import GeoRegion


class GeoRegionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_lagoa(self, lagoa: str, only_active: bool = True) -> list[GeoRegion]:
        q = self._db.query(GeoRegion).filter(GeoRegion.lagoa == lagoa)
        if only_active:
            q = q.filter(GeoRegion.ativo == 1)
        return q.order_by(GeoRegion.nome).all()

    def get_all(self, only_active: bool = False) -> list[GeoRegion]:
        q = self._db.query(GeoRegion)
        if only_active:
            q = q.filter(GeoRegion.ativo == 1)
        return q.order_by(GeoRegion.lagoa, GeoRegion.nome).all()

    def get_by_id(self, region_id: int) -> GeoRegion | None:
        return self._db.query(GeoRegion).filter(GeoRegion.id == region_id).first()

    def create(self, **kwargs) -> GeoRegion:
        region = GeoRegion(**kwargs)
        self._db.add(region)
        self._db.commit()
        self._db.refresh(region)
        return region

    def update(self, region_id: int, **kwargs) -> GeoRegion | None:
        region = self.get_by_id(region_id)
        if not region:
            return None
        for k, v in kwargs.items():
            setattr(region, k, v)
        region.atualizado_em = datetime.utcnow()
        self._db.commit()
        self._db.refresh(region)
        return region

    def delete(self, region_id: int) -> bool:
        region = self.get_by_id(region_id)
        if not region:
            return False
        self._db.delete(region)
        self._db.commit()
        return True
