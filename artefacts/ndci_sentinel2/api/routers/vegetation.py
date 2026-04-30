"""
Router: /api/vegetation — série temporal de NDVI no anel de vegetação terrestre.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from storage.database import get_db
from storage.repositories.ndvi import NdviRepository

router = APIRouter(prefix="/api/vegetation", tags=["Vegetation"])


@router.get("")
def get_vegetation(
    lagoa: Optional[str] = None,
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """
    Série mensal de NDVI por lagoa.

    Query params:
      lagoa     — filtra por lagoa específica (default: todas)
      satellite — satélite de origem (default: sentinel2)

    Retorna: { "Lagoa X": { periodos, ndvi_mean, ndvi_p90, ndvi_p10, n_pixels } }
    """
    repo = NdviRepository(db)

    if lagoa:
        records = repo.get_monthly_series(lagoa=lagoa, satellite=satellite)
        if not records:
            raise HTTPException(
                404,
                f"Nenhum dado de vegetação para lagoa='{lagoa}'. "
                f"Execute POST /api/workers/collect-ndvi para iniciar a ingestão.",
            )
        series_map = {lagoa: records}
    else:
        series_map = repo.get_all_monthly_series(satellite=satellite)

    return {
        lg: {
            "periodos":  [f"{r.ano}-{r.mes:02d}" for r in recs],
            "ndvi_mean": [r.ndvi_mean for r in recs],
            "ndvi_p90":  [r.ndvi_p90  for r in recs],
            "ndvi_p10":  [r.ndvi_p10  for r in recs],
            "n_pixels":  [r.n_pixels  for r in recs],
        }
        for lg, recs in series_map.items()
    }


@router.get("/{lagoa}/images")
def get_vegetation_images(
    lagoa: str,
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """
    Série de NDVI por imagem individual (granularidade diária).

    Retorna: { lagoa, satellite, n_images, datas, ndvi_mean, ndvi_p90, ndvi_p10, n_pixels, cloud_pct }
    """
    repo    = NdviRepository(db)
    records = repo.get_image_series(lagoa=lagoa, satellite=satellite)

    if not records:
        raise HTTPException(
            404,
            f"Nenhum dado de vegetação por imagem para lagoa='{lagoa}'. "
            f"Execute POST /api/workers/collect-ndvi para iniciar a ingestão.",
        )

    return {
        "lagoa":     lagoa,
        "satellite": satellite,
        "n_images":  len(records),
        "datas":     [r.data.isoformat() for r in records],
        "ndvi_mean": [r.ndvi_mean for r in records],
        "ndvi_p90":  [r.ndvi_p90  for r in records],
        "ndvi_p10":  [r.ndvi_p10  for r in records],
        "n_pixels":  [r.n_pixels  for r in records],
        "cloud_pct": [r.cloud_pct for r in records],
    }


@router.get("/lagoas")
def list_vegetation_lagoas(
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """Lagoas com dados de vegetação disponíveis."""
    repo = NdviRepository(db)
    return {"lagoas": repo.available_lagoas(satellite=satellite)}
