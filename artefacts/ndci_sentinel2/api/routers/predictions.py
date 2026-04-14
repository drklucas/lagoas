"""
Router: /api/predictions — previsão de NDCI por lagoa.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ml.features import load_ndci_features, LAGOA_MUNICIPIO
from ml.predictor import NdciPredictor
from storage.database import get_db

router = APIRouter(prefix="/api/predictions", tags=["Predictions"])


@router.get("/ndci/{lagoa}")
def predict_ndci(
    lagoa: str,
    horizonte_meses: int = 2,
    satellite: str = "sentinel2",
    db: Session = Depends(get_db),
):
    """
    Previsão de NDCI para uma lagoa (horizonte 1–2 meses).

    Treina o modelo sob demanda com os dados disponíveis no banco e retorna
    a previsão iterativa multi-passo com IC 80%.

    Path param:
      lagoa — nome da lagoa (ex: "Lagoa Itapeva")

    Query params:
      horizonte_meses — número de meses à frente (default: 2, max recomendado: 2)
      satellite       — satélite de origem (default: sentinel2)

    Resposta:
    [
      {
        "ano_alvo": 2024,
        "mes_alvo": 3,
        "horizonte_meses": 1,
        "valor_previsto": 0.085,
        "intervalo_inferior": 0.042,
        "intervalo_superior": 0.128
      },
      ...
    ]
    """
    if lagoa not in LAGOA_MUNICIPIO:
        raise HTTPException(404, f"Lagoa '{lagoa}' não encontrada. Disponíveis: {list(LAGOA_MUNICIPIO.keys())}")

    horizonte_meses = max(1, min(horizonte_meses, 6))

    df = load_ndci_features(lagoa=lagoa, satellite=satellite)
    if df is None or df.empty:
        raise HTTPException(
            422,
            f"Sem dados históricos para '{lagoa}'. "
            f"Execute POST /api/workers/collect-stats primeiro.",
        )

    predictor = NdciPredictor()
    try:
        metrics = predictor.fit(df)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    forecasts = predictor.predict(horizonte_meses=horizonte_meses)
    return {
        "lagoa":      lagoa,
        "satellite":  satellite,
        "metrics":    metrics,
        "forecasts":  forecasts,
    }
