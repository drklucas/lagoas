"""
Repositório para registros de NDVI no anel de vegetação terrestre.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from storage.models import NdviRecord, NdviMonthlyRecord


class NdviRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Escrita ───────────────────────────────────────────────────────────────

    def upsert_image(
        self,
        *,
        satellite: str,
        lagoa: str,
        data: date,
        ndvi_mean: float | None,
        ndvi_p90: float | None,
        ndvi_p10: float | None,
        n_pixels: int | None,
        cloud_pct: float | None,
    ) -> None:
        existing = (
            self.db.query(NdviRecord)
            .filter_by(satellite=satellite, lagoa=lagoa, data=data)
            .first()
        )
        if existing:
            existing.ndvi_mean = ndvi_mean
            existing.ndvi_p90  = ndvi_p90
            existing.ndvi_p10  = ndvi_p10
            existing.n_pixels  = n_pixels
            existing.cloud_pct = cloud_pct
        else:
            self.db.add(NdviRecord(
                satellite=satellite,
                lagoa=lagoa,
                data=data,
                ano=data.year,
                mes=data.month,
                ndvi_mean=ndvi_mean,
                ndvi_p90=ndvi_p90,
                ndvi_p10=ndvi_p10,
                n_pixels=n_pixels,
                cloud_pct=cloud_pct,
            ))
        self.db.commit()

    def upsert_monthly(
        self,
        *,
        satellite: str,
        lagoa: str,
        ano: int,
        mes: int,
        ndvi_mean: float | None,
        ndvi_p90: float | None,
        ndvi_p10: float | None,
        n_pixels: int | None,
    ) -> None:
        existing = (
            self.db.query(NdviMonthlyRecord)
            .filter_by(satellite=satellite, lagoa=lagoa, ano=ano, mes=mes)
            .first()
        )
        if existing:
            existing.ndvi_mean    = ndvi_mean
            existing.ndvi_p90     = ndvi_p90
            existing.ndvi_p10     = ndvi_p10
            existing.n_pixels     = n_pixels
            existing.collected_at = datetime.utcnow()
        else:
            self.db.add(NdviMonthlyRecord(
                satellite=satellite,
                lagoa=lagoa,
                ano=ano,
                mes=mes,
                ndvi_mean=ndvi_mean,
                ndvi_p90=ndvi_p90,
                ndvi_p10=ndvi_p10,
                n_pixels=n_pixels,
                collected_at=datetime.utcnow(),
            ))
        self.db.commit()

    # ── Leitura ───────────────────────────────────────────────────────────────

    def exists(self, satellite: str, lagoa: str, data: date) -> bool:
        return bool(
            self.db.query(NdviRecord.id)
            .filter_by(satellite=satellite, lagoa=lagoa, data=data)
            .first()
        )

    def get_image_series(self, lagoa: str, satellite: str = "sentinel2") -> list[NdviRecord]:
        return (
            self.db.query(NdviRecord)
            .filter_by(satellite=satellite, lagoa=lagoa)
            .order_by(NdviRecord.data)
            .all()
        )

    def get_monthly_series(self, lagoa: str, satellite: str = "sentinel2") -> list[NdviMonthlyRecord]:
        return (
            self.db.query(NdviMonthlyRecord)
            .filter_by(satellite=satellite, lagoa=lagoa)
            .order_by(NdviMonthlyRecord.ano, NdviMonthlyRecord.mes)
            .all()
        )

    def get_all_monthly_series(self, satellite: str = "sentinel2") -> dict[str, list[NdviMonthlyRecord]]:
        rows = (
            self.db.query(NdviMonthlyRecord)
            .filter_by(satellite=satellite)
            .order_by(NdviMonthlyRecord.lagoa, NdviMonthlyRecord.ano, NdviMonthlyRecord.mes)
            .all()
        )
        result: dict[str, list] = {}
        for r in rows:
            result.setdefault(r.lagoa, []).append(r)
        return result

    def get_monthly_aggregation(self, lagoa: str, satellite: str = "sentinel2") -> list[dict[str, Any]]:
        """GROUP BY mensal sobre NdviRecord — fonte para upsert_monthly."""
        rows = (
            self.db.query(
                NdviRecord.ano,
                NdviRecord.mes,
                func.avg(NdviRecord.ndvi_mean).label("ndvi_mean"),
                func.avg(NdviRecord.ndvi_p90).label("ndvi_p90"),
                func.avg(NdviRecord.ndvi_p10).label("ndvi_p10"),
                func.sum(NdviRecord.n_pixels).label("n_pixels"),
            )
            .filter_by(satellite=satellite, lagoa=lagoa)
            .group_by(NdviRecord.ano, NdviRecord.mes)
            .order_by(NdviRecord.ano, NdviRecord.mes)
            .all()
        )
        return [
            {
                "ano":       r.ano,
                "mes":       r.mes,
                "ndvi_mean": r.ndvi_mean,
                "ndvi_p90":  r.ndvi_p90,
                "ndvi_p10":  r.ndvi_p10,
                "n_pixels":  r.n_pixels,
            }
            for r in rows
        ]

    def available_lagoas(self, satellite: str = "sentinel2") -> list[str]:
        rows = (
            self.db.query(NdviMonthlyRecord.lagoa)
            .filter_by(satellite=satellite)
            .distinct()
            .order_by(NdviMonthlyRecord.lagoa)
            .all()
        )
        return [r.lagoa for r in rows]
