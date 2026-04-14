"""
Router: /api/water-quality — série temporal e status atual por lagoa.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.index_registry import classify
from storage.database import get_db
from storage.repositories.water_quality import WaterQualityRepository

router = APIRouter(prefix="/api/water-quality", tags=["Water Quality"])


@router.get("")
def get_water_quality(
    lagoa: Optional[str] = None,
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """
    Série mensal completa de qualidade da água.

    Retorna arrays de ndci_mean, ndci_p90, turbidez, fai_mean, ndwi_mean,
    n_pixels e periodos (YYYY-MM) por lagoa.

    Query params:
      lagoa    — filtra por lagoa específica (default: todas)
      satellite — satélite de origem (default: sentinel2)

    Exemplo de resposta:
    {
      "Lagoa Itapeva": {
        "periodos":  ["2017-01", "2017-02", ...],
        "ndci_mean": [0.032, 0.045, ...],
        ...
      }
    }
    """
    repo = WaterQualityRepository(db)

    if lagoa:
        records = repo.get_series(lagoa=lagoa, satellite=satellite)
        if not records:
            raise HTTPException(404, f"Nenhum dado para lagoa='{lagoa}'.")
        series_map = {lagoa: records}
    else:
        series_map = repo.get_all_series(satellite=satellite)

    result: dict = {}
    for lg, recs in series_map.items():
        result[lg] = {
            "periodos":   [f"{r.ano}-{r.mes:02d}" for r in recs],
            "ndci_mean":  [r.ndci_mean  for r in recs],
            "ndci_p90":   [r.ndci_p90   for r in recs],
            "turbidez":   [r.ndti_mean  for r in recs],
            "fai_mean":   [r.fai_mean   for r in recs],
            "ndwi_mean":  [r.ndwi_mean  for r in recs],
            "n_pixels":   [r.n_pixels   for r in recs],
        }
    return result


@router.get("/current")
def get_current_status(
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """
    Status atual de cada lagoa — último mês com dados disponíveis.

    Retorna para cada lagoa:
      periodo    — YYYY-MM do último dado
      ndci_mean  — valor médio
      status     — classificação de alerta: bom | moderado | elevado | critico | sem_dados
      ...
    """
    repo    = WaterQualityRepository(db)
    latest  = repo.get_latest(satellite=satellite)

    result: dict = {}
    for r in latest:
        result[r.lagoa] = {
            "lagoa":      r.lagoa,
            "periodo":    f"{r.ano}-{r.mes:02d}",
            "ndci_mean":  r.ndci_mean,
            "ndci_p90":   r.ndci_p90,
            "turbidez":   r.ndti_mean,
            "fai_mean":   r.fai_mean,
            "ndwi_mean":  r.ndwi_mean,
            "n_pixels":   r.n_pixels,
            "status":     classify("ndci", r.ndci_mean),
        }
    return result


@router.get("/lagoas")
def list_lagoas(
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """Lista de lagoas com dados disponíveis no banco."""
    repo = WaterQualityRepository(db)
    return {"lagoas": repo.available_lagoas(satellite=satellite)}
