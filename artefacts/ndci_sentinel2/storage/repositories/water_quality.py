"""
Repositório para WaterQualityRecord — CRUD e queries de série temporal.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from storage.models import WaterQualityRecord


class WaterQualityRepository:
    """Acesso à tabela ndci_water_quality."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Escrita ───────────────────────────────────────────────────────────────

    def upsert(
        self,
        *,
        satellite: str,
        lagoa: str,
        ano: int,
        mes: int,
        ndci_mean: float | None,
        ndci_p90: float | None,
        ndti_mean: float | None,
        fai_mean: float | None,
        ndwi_mean: float | None,
        n_pixels: int | None,
    ) -> WaterQualityRecord:
        """Insere ou atualiza um registro de qualidade da água."""
        rec = (
            self._db.query(WaterQualityRecord)
            .filter_by(satellite=satellite, lagoa=lagoa, ano=ano, mes=mes)
            .first()
        )
        if rec:
            rec.ndci_mean    = ndci_mean
            rec.ndci_p90     = ndci_p90
            rec.ndti_mean    = ndti_mean
            rec.fai_mean     = fai_mean
            rec.ndwi_mean    = ndwi_mean
            rec.n_pixels     = n_pixels
            rec.collected_at = datetime.utcnow()
        else:
            rec = WaterQualityRecord(
                satellite=satellite,
                lagoa=lagoa,
                ano=ano,
                mes=mes,
                ndci_mean=ndci_mean,
                ndci_p90=ndci_p90,
                ndti_mean=ndti_mean,
                fai_mean=fai_mean,
                ndwi_mean=ndwi_mean,
                n_pixels=n_pixels,
            )
            self._db.add(rec)
        self._db.commit()
        return rec

    # ── Leitura ───────────────────────────────────────────────────────────────

    def get_series(
        self,
        lagoa: str,
        satellite: str = "sentinel2",
    ) -> list[WaterQualityRecord]:
        """Retorna toda a série temporal de uma lagoa, ordenada por período."""
        return (
            self._db.query(WaterQualityRecord)
            .filter_by(satellite=satellite, lagoa=lagoa)
            .order_by(WaterQualityRecord.ano, WaterQualityRecord.mes)
            .all()
        )

    def get_all_series(
        self,
        satellite: str = "sentinel2",
    ) -> dict[str, list[WaterQualityRecord]]:
        """Retorna a série temporal de todas as lagoas."""
        rows = (
            self._db.query(WaterQualityRecord)
            .filter_by(satellite=satellite)
            .order_by(
                WaterQualityRecord.lagoa,
                WaterQualityRecord.ano,
                WaterQualityRecord.mes,
            )
            .all()
        )
        result: dict[str, list[WaterQualityRecord]] = {}
        for r in rows:
            result.setdefault(r.lagoa, []).append(r)
        return result

    def get_latest(
        self,
        satellite: str = "sentinel2",
    ) -> list[WaterQualityRecord]:
        """
        Retorna o registro mais recente de cada lagoa.
        Implementado como subquery para evitar N+1.
        """
        from sqlalchemy import func

        subq = (
            self._db.query(
                WaterQualityRecord.lagoa,
                func.max(WaterQualityRecord.ano * 100 + WaterQualityRecord.mes).label("max_periodo"),
            )
            .filter_by(satellite=satellite)
            .group_by(WaterQualityRecord.lagoa)
            .subquery()
        )

        return (
            self._db.query(WaterQualityRecord)
            .join(
                subq,
                (WaterQualityRecord.lagoa == subq.c.lagoa)
                & (
                    WaterQualityRecord.ano * 100 + WaterQualityRecord.mes
                    == subq.c.max_periodo
                ),
            )
            .all()
        )

    def available_lagoas(self, satellite: str = "sentinel2") -> list[str]:
        """Lista de lagoas com pelo menos um registro."""
        rows = (
            self._db.query(WaterQualityRecord.lagoa)
            .filter_by(satellite=satellite)
            .distinct()
            .all()
        )
        return sorted(r[0] for r in rows)
