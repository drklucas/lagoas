"""
Router de análises estatísticas — Mann-Kendall Sazonal + CUSUM.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from analytics.mann_kendall import MKResult, seasonal_mann_kendall
from analytics.cusum import cusum_analysis
from storage.database import get_db
from storage.repositories.image_records import ImageRecordRepository
from storage.repositories.water_quality import WaterQualityRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_INDEX_MAP: dict[str, str] = {
    "ndci": "ndci_mean",
    "ndti": "ndti_mean",
    "ndwi": "ndwi_mean",
    "fai":  "fai_mean",
}

_INDEX_LABELS: dict[str, str] = {
    "ndci": "NDCI — Clorofila",
    "ndti": "NDTI — Turbidez",
    "ndwi": "NDWI — Corpo d'Água",
    "fai":  "FAI — Algas Flutuantes",
}


def _mk_to_dict(r: MKResult) -> dict:
    return {
        "trend":                  r.trend,
        "significativo":          r.significativo,
        "p_value":                r.p_value,
        "z_score":                r.z_score,
        "s_stat":                 r.s_stat,
        "tau":                    r.tau,
        "sen_slope_mes":          r.sen_slope_mes,
        "sen_slope_ano":          r.sen_slope_ano,
        "n_obs":                  r.n_obs,
        "n_seasons_com_dados":    r.n_seasons_com_dados,
        "periodo_inicio":         r.periodo_inicio,
        "periodo_fim":            r.periodo_fim,
        "alpha":                  r.alpha,
        "n_outliers_removidos":   r.n_outliers_removidos,
        "outliers":               r.outliers,
        "avisos":                 r.avisos,
        "erro":                   r.erro,
    }


@router.get("/summary")
def get_summary(
    satellite: str = Query("sentinel2"),
    alpha: float = Query(0.05, ge=0.01, le=0.10),
    db: Session = Depends(get_db),
):
    """
    Seasonal Mann-Kendall summary for all lagoas and all indices.

    Returns nested dict: { lagoa → { index → MKResult } }
    Used to populate the analytics tab overview table.
    """
    repo = WaterQualityRepository(db)
    all_series = repo.get_all_series(satellite=satellite)

    lagoas_result: dict[str, dict] = {}
    for lagoa, records in all_series.items():
        lagoas_result[lagoa] = {}
        for idx_key, col_name in _INDEX_MAP.items():
            values = [getattr(r, col_name) for r in records]
            months = [r.mes for r in records]
            years  = [r.ano for r in records]
            mk = seasonal_mann_kendall(values, months, years, alpha=alpha)
            lagoas_result[lagoa][idx_key] = {
                "label": _INDEX_LABELS[idx_key],
                **_mk_to_dict(mk),
            }

    return {"satellite": satellite, "alpha": alpha, "lagoas": lagoas_result}


@router.get("/{lagoa}/trend")
def get_trend(
    lagoa: str,
    satellite: str = Query("sentinel2"),
    alpha: float = Query(0.05, ge=0.01, le=0.10),
    db: Session = Depends(get_db),
):
    """
    Seasonal Mann-Kendall trend test for all water quality indices of a lagoa.

    Uses monthly aggregated data (ndci_water_quality) and returns trend
    direction, significance, Z-score, and Sen's slope per year for
    NDCI, NDTI, NDWI, and FAI.

    Reference: Hirsch et al. (1982); Sen (1968).
    """
    repo = WaterQualityRepository(db)
    records = repo.get_series(lagoa, satellite=satellite)

    if not records:
        return {
            "lagoa": lagoa,
            "satellite": satellite,
            "indices": {},
            "erro": "Sem dados para esta lagoa",
        }

    indices: dict[str, dict] = {}
    for idx_key, col_name in _INDEX_MAP.items():
        values = [getattr(r, col_name) for r in records]
        months = [r.mes for r in records]
        years  = [r.ano for r in records]
        mk = seasonal_mann_kendall(values, months, years, alpha=alpha)
        indices[idx_key] = {"label": _INDEX_LABELS[idx_key], **_mk_to_dict(mk)}

    return {"lagoa": lagoa, "satellite": satellite, "alpha": alpha, "indices": indices}


@router.get("/{lagoa}/changepoint")
def get_changepoint(
    lagoa: str,
    index: str = Query("ndci"),
    satellite: str = Query("sentinel2"),
    use_images: bool = Query(True),
    k_fator: float = Query(0.5, ge=0.1, le=2.0),
    h_fator: float = Query(4.0, ge=1.0, le=10.0),
    db: Session = Depends(get_db),
):
    """
    CUSUM change-point detection for the specified index and lagoa.

    When use_images=True (default), uses individual Sentinel-2 acquisitions
    from ndci_image_records for higher temporal resolution (~10-day intervals).
    Otherwise uses monthly aggregates from ndci_water_quality.

    CUSUM parameters:
      k = k_fator × σ_baseline  (reference value; default 0.5σ)
      h = h_fator × σ_baseline  (decision interval; default 4σ)

    Reference: Page (1954).
    """
    if index not in _INDEX_MAP:
        return {"erro": f"Índice '{index}' não reconhecido. Use: {list(_INDEX_MAP)}"}

    col_name = _INDEX_MAP[index]

    if use_images:
        repo_img = ImageRecordRepository(db)
        records  = repo_img.get_series(lagoa, satellite=satellite)
        values   = [getattr(r, col_name) for r in records]
        periodos = [r.data.isoformat() for r in records]
    else:
        repo_wq = WaterQualityRepository(db)
        records  = repo_wq.get_series(lagoa, satellite=satellite)
        values   = [getattr(r, col_name) for r in records]
        periodos = [f"{r.ano}-{r.mes:02d}" for r in records]

    if not records:
        return {
            "lagoa": lagoa,
            "index": index,
            "satellite": satellite,
            "erro": "Sem dados para esta lagoa",
        }

    result = cusum_analysis(
        values=values,
        periodos=periodos,
        k_fator=k_fator,
        h_fator=h_fator,
    )

    return {
        "lagoa":         lagoa,
        "index":         index,
        "index_label":   _INDEX_LABELS[index],
        "satellite":     satellite,
        "granularidade": "imagem" if use_images else "mensal",
        "baseline": {
            "n_obs":       result.n_baseline,
            "mean":        result.baseline_mean,
            "std":         result.baseline_std,
            "periodo":     result.periodo_baseline,
            "estimador":   result.baseline_estimador,
            "aviso_contaminado":  result.aviso_baseline_contaminado,
            "outliers":    result.outliers_baseline,
        },
        "parametros": {
            "k":       result.k,
            "h":       result.h,
            "k_fator": result.k_fator,
            "h_fator": result.h_fator,
        },
        "alarmes": [
            {
                "periodo":           a.periodo,
                "tipo":              a.tipo,
                "cusum_value":       a.cusum_value,
                "data_inicio_shift": a.data_inicio_shift,
            }
            for a in result.alarmes
        ],
        "series": {
            "periodos":      result.periodos,
            "valores":       result.valores,
            "cusum_pos":     result.cusum_pos,
            "cusum_neg":     result.cusum_neg,
            "h":             result.h,
            "baseline_mean": result.baseline_mean,
        },
        "n_obs": result.n_obs,
        "erro":  result.erro,
    }
