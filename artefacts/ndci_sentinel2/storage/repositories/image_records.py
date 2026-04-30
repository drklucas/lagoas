"""
Repositório para ImageRecord — CRUD e queries de série temporal por imagem.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from storage.models import ImageRecord


class ImageRecordRepository:
    """Acesso à tabela ndci_image_records."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Escrita ───────────────────────────────────────────────────────────────

    def upsert(
        self,
        *,
        satellite: str,
        lagoa: str,
        data: date,
        ndci_mean: float | None,
        ndci_p90: float | None,
        ndci_p10: float | None,
        ndti_mean: float | None,
        ndwi_mean: float | None,
        fai_mean: float | None,
        n_pixels: int | None,
        cloud_pct: float | None,
        zona: str = "total",
    ) -> ImageRecord:
        """Insere ou atualiza um registro por imagem individual."""
        rec = (
            self._db.query(ImageRecord)
            .filter_by(satellite=satellite, lagoa=lagoa, data=data, zona=zona)
            .first()
        )
        if rec:
            rec.ndci_mean  = ndci_mean
            rec.ndci_p90   = ndci_p90
            rec.ndci_p10   = ndci_p10
            rec.ndti_mean  = ndti_mean
            rec.ndwi_mean  = ndwi_mean
            rec.fai_mean   = fai_mean
            rec.n_pixels   = n_pixels
            rec.cloud_pct  = cloud_pct
            rec.created_at = datetime.utcnow()
        else:
            rec = ImageRecord(
                satellite=satellite,
                lagoa=lagoa,
                zona=zona,
                data=data,
                ano=data.year,
                mes=data.month,
                ndci_mean=ndci_mean,
                ndci_p90=ndci_p90,
                ndci_p10=ndci_p10,
                ndti_mean=ndti_mean,
                ndwi_mean=ndwi_mean,
                fai_mean=fai_mean,
                n_pixels=n_pixels,
                cloud_pct=cloud_pct,
            )
            self._db.add(rec)
        self._db.commit()
        return rec

    # ── Leitura ───────────────────────────────────────────────────────────────

    def get_series(
        self,
        lagoa: str,
        satellite: str = "sentinel2",
        zona: str = "total",
    ) -> list[ImageRecord]:
        """Retorna toda a série por imagem de uma lagoa, ordenada por data."""
        return (
            self._db.query(ImageRecord)
            .filter_by(satellite=satellite, lagoa=lagoa, zona=zona)
            .order_by(ImageRecord.data)
            .all()
        )

    def get_all_series(
        self,
        satellite: str = "sentinel2",
        zona: str = "total",
    ) -> dict[str, list[ImageRecord]]:
        """Retorna registros por imagem de todas as lagoas para uma zona."""
        rows = (
            self._db.query(ImageRecord)
            .filter_by(satellite=satellite, zona=zona)
            .order_by(ImageRecord.lagoa, ImageRecord.data)
            .all()
        )
        result: dict[str, list[ImageRecord]] = {}
        for r in rows:
            result.setdefault(r.lagoa, []).append(r)
        return result

    def get_zones_series(
        self,
        lagoa: str,
        satellite: str = "sentinel2",
    ) -> dict[str, list[ImageRecord]]:
        """Retorna séries por imagem agrupadas por zona (exclui 'total')."""
        rows = (
            self._db.query(ImageRecord)
            .filter(
                ImageRecord.satellite == satellite,
                ImageRecord.lagoa == lagoa,
                ImageRecord.zona != "total",
            )
            .order_by(ImageRecord.zona, ImageRecord.data)
            .all()
        )
        result: dict[str, list[ImageRecord]] = {}
        for r in rows:
            result.setdefault(r.zona, []).append(r)
        return result

    def get_monthly_aggregation(
        self,
        lagoa: str,
        satellite: str = "sentinel2",
        zona: str = "total",
    ) -> list[dict]:
        """
        Agrega os registros por imagem em resumos mensais para uma zona.

        Retorna lista de dicts com ano, mes, ndci_mean (média das imagens
        do mês), ndci_p90 (máximo dos P90 individuais), ndci_p10 (mínimo dos
        P10 individuais), ndti_mean, fai_mean, ndwi_mean e n_pixels (soma).
        """
        rows = (
            self._db.query(
                ImageRecord.ano,
                ImageRecord.mes,
                func.avg(ImageRecord.ndci_mean).label("ndci_mean"),
                func.max(ImageRecord.ndci_p90).label("ndci_p90"),
                func.min(ImageRecord.ndci_p10).label("ndci_p10"),
                func.avg(ImageRecord.ndti_mean).label("ndti_mean"),
                func.avg(ImageRecord.fai_mean).label("fai_mean"),
                func.avg(ImageRecord.ndwi_mean).label("ndwi_mean"),
                func.sum(ImageRecord.n_pixels).label("n_pixels"),
                func.count(ImageRecord.id).label("n_images"),
            )
            .filter_by(satellite=satellite, lagoa=lagoa, zona=zona)
            .group_by(ImageRecord.ano, ImageRecord.mes)
            .order_by(ImageRecord.ano, ImageRecord.mes)
            .all()
        )
        return [
            {
                "ano":       r.ano,
                "mes":       r.mes,
                "ndci_mean": r.ndci_mean,
                "ndci_p90":  r.ndci_p90,
                "ndci_p10":  r.ndci_p10,
                "ndti_mean": r.ndti_mean,
                "fai_mean":  r.fai_mean,
                "ndwi_mean": r.ndwi_mean,
                "n_pixels":  r.n_pixels,
                "n_images":  r.n_images,
            }
            for r in rows
        ]

    def exists(
        self,
        satellite: str,
        lagoa: str,
        data: date,
        zona: str = "total",
    ) -> bool:
        """Verifica se já existe registro para esta cena e zona."""
        return (
            self._db.query(ImageRecord.id)
            .filter_by(satellite=satellite, lagoa=lagoa, data=data, zona=zona)
            .first()
        ) is not None
