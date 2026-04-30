"""
Router: /api/water-quality — série temporal e status atual por lagoa.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.index_registry import classify
from storage.database import get_db
from storage.repositories.image_records import ImageRecordRepository
from storage.repositories.water_quality import WaterQualityRepository

router = APIRouter(prefix="/api/water-quality", tags=["Water Quality"])


@router.get("")
def get_water_quality(
    lagoa: Optional[str] = None,
    satellite: str = "sentinel2",
    zona: str = "total",
    db: Session = Depends(get_db),
):
    """
    Série mensal completa de qualidade da água.

    Query params:
      lagoa    — filtra por lagoa específica (default: todas)
      satellite — satélite de origem (default: sentinel2)
      zona      — zona espacial: "total" | "margem" | "medio" | "nucleo" (default: total)
    """
    repo = WaterQualityRepository(db)

    if lagoa:
        records = repo.get_series(lagoa=lagoa, satellite=satellite, zona=zona)
        if not records:
            raise HTTPException(404, f"Nenhum dado para lagoa='{lagoa}' zona='{zona}'.")
        series_map = {lagoa: records}
    else:
        series_map = repo.get_all_series(satellite=satellite, zona=zona)

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


@router.get("/zones/available")
def get_available_zones(
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """Lista de zonas distintas presentes no banco (total + zonas nomeadas)."""
    repo = WaterQualityRepository(db)
    return {"zones": repo.available_zones(satellite=satellite)}


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


@router.get("/images")
def get_all_image_series(
    lagoa: Optional[str] = None,
    satellite: str = "sentinel2",
    zona: str = "total",
    db: Session = Depends(get_db),
):
    """
    Série por imagem individual — todas as lagoas (ou filtrada por lagoa/zona).

    Retorna dict { lagoa: { datas, ndci_mean, ndci_p90, ndci_p10,
                            ndti_mean, ndwi_mean, fai_mean, n_pixels, cloud_pct } }
    """
    repo = ImageRecordRepository(db)

    if lagoa:
        records = repo.get_series(lagoa=lagoa, satellite=satellite, zona=zona)
        series_map = {lagoa: records} if records else {}
    else:
        series_map = repo.get_all_series(satellite=satellite, zona=zona)

    result: dict = {}
    for lg, recs in series_map.items():
        result[lg] = {
            "datas":     [r.data.isoformat() for r in recs],
            "ndci_mean": [r.ndci_mean  for r in recs],
            "ndci_p90":  [r.ndci_p90   for r in recs],
            "ndci_p10":  [r.ndci_p10   for r in recs],
            "ndti_mean": [r.ndti_mean  for r in recs],
            "fai_mean":  [r.fai_mean   for r in recs],
            "ndwi_mean": [r.ndwi_mean  for r in recs],
            "n_pixels":  [r.n_pixels   for r in recs],
            "cloud_pct": [r.cloud_pct  for r in recs],
        }
    return result


@router.get("/{lagoa}/zones")
def get_zone_series(
    lagoa: str,
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """
    Série mensal por zona espacial (margem / medio / nucleo) de uma lagoa.

    Retorna um objeto com uma chave por zona, cada uma contendo
    periodos, ndci_mean, ndci_p90, turbidez, fai_mean, n_pixels.
    Zonas sem dados não aparecem na resposta.
    """
    repo  = WaterQualityRepository(db)
    zones = repo.get_zones_series(lagoa=lagoa, satellite=satellite)

    if not zones:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum dado por zona para lagoa='{lagoa}'. "
                   f"Execute /api/workers/collect-stats para iniciar a ingestão.",
        )

    result: dict = {}
    for zona_nome, recs in zones.items():
        result[zona_nome] = {
            "periodos":  [f"{r.ano}-{r.mes:02d}" for r in recs],
            "ndci_mean": [r.ndci_mean for r in recs],
            "ndci_p90":  [r.ndci_p90  for r in recs],
            "turbidez":  [r.ndti_mean for r in recs],
            "fai_mean":  [r.fai_mean  for r in recs],
            "ndwi_mean": [r.ndwi_mean for r in recs],
            "n_pixels":  [r.n_pixels  for r in recs],
        }
    return {"lagoa": lagoa, "satellite": satellite, "zonas": result}


@router.get("/{lagoa}/images")
def get_image_series(
    lagoa: str,
    satellite: str = "sentinel2",
    zona: str = "total",
    db: Session = Depends(get_db),
):
    """
    Série temporal por imagem individual de uma lagoa.

    Retorna um registro por cena Sentinel-2 válida coletada, com
    granularidade de data (YYYY-MM-DD) em vez de período mensal.
    Inclui P10 e P90 do NDCI por imagem para análise de variabilidade.

    Query params:
      zona — zona espacial: "total" | "margem" | "medio" | "nucleo" | <nome_regiao> (default: total)

    Endpoint alinhado com Pi & Guasselli (SBSR 2025).
    """
    repo    = ImageRecordRepository(db)
    records = repo.get_series(lagoa=lagoa, satellite=satellite, zona=zona)

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum dado por imagem para lagoa='{lagoa}' zona='{zona}'. "
                   f"Execute /api/workers/collect-stats para iniciar a ingestão.",
        )

    return {
        "lagoa":     lagoa,
        "satellite": satellite,
        "zona":      zona,
        "n_images":  len(records),
        "datas":     [r.data.isoformat() for r in records],
        "ndci_mean": [r.ndci_mean  for r in records],
        "ndci_p90":  [r.ndci_p90   for r in records],
        "ndci_p10":  [r.ndci_p10   for r in records],
        "ndti_mean": [r.ndti_mean  for r in records],
        "fai_mean":  [r.fai_mean   for r in records],
        "ndwi_mean": [r.ndwi_mean  for r in records],
        "n_pixels":  [r.n_pixels   for r in records],
        "cloud_pct": [r.cloud_pct  for r in records],
    }
