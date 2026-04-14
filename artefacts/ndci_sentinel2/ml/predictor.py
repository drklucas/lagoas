"""
Modelo preditivo de NDCI — RandomForest com walk-forward cross-validation.

Standalone: não depende do eyefish. Usa os mesmos algoritmos e hiperparâmetros
documentados em backend/ml/models/qualidade_agua.py do eyefish.

Algoritmo:   RandomForestRegressor (scikit-learn)
Target:      ndci_mean (proxy clorofila-a / cianobactérias)
Granularity: mensal
Horizonte:   1–2 meses (previsão iterativa multi-passo)

Referência técnica: relatorio_ndci.md, seções 9.1–9.5
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit

from ml.features import load_ndci_features, LAGOA_MUNICIPIO

logger = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────────────────────

_EXCLUDE_COLS = {"target", "data", "ano", "mes", "n_pixels"}
_MAX_NULL_RATIO = 0.50

# Clip de segurança: NDCI teórico em [-1, 1]; cortamos em faixa razoável
_NDCI_CLIP_MIN = -0.3
_NDCI_CLIP_MAX =  0.5

# z-score para IC 80% (±1.2816σ)
_Z80 = 1.2816

_RF_PARAMS = dict(
    n_estimators=150,
    max_features="sqrt",
    min_samples_leaf=2,
    random_state=42,
    n_jobs=-1,
)


class NdciPredictor:
    """
    Previsão de NDCI via Random Forest com walk-forward CV.

    Uso típico:
        predictor = NdciPredictor()
        df = load_ndci_features("Lagoa Itapeva")
        metrics = predictor.fit(df)
        forecasts = predictor.predict(horizonte_meses=2)
    """

    def __init__(self) -> None:
        self._model: RandomForestRegressor | None = None
        self._feature_cols: list[str] = []
        self._df_hist: pd.DataFrame | None = None

    # ── 1. Fit ────────────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame) -> dict:
        """
        Walk-forward CV (TimeSeriesSplit n_splits=2) + fit final no conjunto completo.

        Args:
            df: DataFrame retornado por load_ndci_features(), com coluna 'target'.

        Returns:
            {"rmse": float, "mae": float, "n_obs": int}
        """
        df_treino = df[df["target"].notna()].copy()

        if len(df_treino) < 6:
            raise ValueError(
                f"Dados insuficientes para treino: {len(df_treino)} observações "
                f"(mínimo: 6). Execute o worker de coleta de stats primeiro."
            )

        feature_cols = [
            c for c in df_treino.columns
            if c not in _EXCLUDE_COLS
            and pd.api.types.is_numeric_dtype(df_treino[c])
            and df_treino[c].isna().mean() <= _MAX_NULL_RATIO
        ]

        X_df = df_treino[feature_cols].fillna(df_treino[feature_cols].mean()).fillna(0)
        X    = X_df.values
        y    = df_treino["target"].values.astype(float)

        tscv      = TimeSeriesSplit(n_splits=2)
        rmse_list: list[float] = []
        mae_list:  list[float] = []

        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X[train_idx], X[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]

            m = RandomForestRegressor(**_RF_PARAMS)
            m.fit(X_tr, y_tr)
            y_pred = np.clip(m.predict(X_val), _NDCI_CLIP_MIN, _NDCI_CLIP_MAX)

            rmse_list.append(float(np.sqrt(mean_squared_error(y_val, y_pred))))
            mae_list.append(float(mean_absolute_error(y_val, y_pred)))

        # Fit final no conjunto completo
        model_final = RandomForestRegressor(**_RF_PARAMS)
        model_final.fit(X, y)

        self._model        = model_final
        self._feature_cols = feature_cols
        self._df_hist      = df_treino.copy()

        metrics = {
            "rmse":  round(float(np.mean(rmse_list)), 6),
            "mae":   round(float(np.mean(mae_list)),  6),
            "n_obs": len(X),
        }
        logger.info("NdciPredictor.fit: %s", metrics)
        return metrics

    # ── 2. Predict ────────────────────────────────────────────────────────────

    def predict(self, horizonte_meses: int = 2) -> list[dict]:
        """
        Previsão iterativa multi-passo com IC 80% via std das árvores.

        Para horizonte > 1 mês, a previsão do passo anterior alimenta os lags
        do passo seguinte:
          h=1: lag1=real[-1],    lag2=real[-2]
          h=2: lag1=prev[0],     lag2=real[-1]
          h=N: lag1=prev[N-2],   lag2=prev[N-3]

        Returns:
            Lista de dicts, um por horizonte:
            {
                "ano_alvo":           int,
                "mes_alvo":           int,
                "horizonte_meses":    int,
                "valor_previsto":     float,
                "intervalo_inferior": float,   # IC 80%
                "intervalo_superior": float,
            }
        """
        if self._model is None or self._df_hist is None:
            raise RuntimeError("Chame fit() antes de predict().")

        df   = self._df_hist
        last = df.iloc[-1]
        last_ano = int(last["ano"])
        last_mes = int(last["mes"])

        real_ndci     = df["target"].values.tolist()
        ndci_lag1_real = float(real_ndci[-1]) if len(real_ndci) >= 1 else 0.0
        ndci_lag2_real = float(real_ndci[-2]) if len(real_ndci) >= 2 else 0.0

        def _last_val(col: str) -> float:
            if col not in df.columns:
                return 0.0
            s = df[col].dropna()
            return float(s.iloc[-1]) if not s.empty else 0.0

        def _mes_mean(col: str, mes: int) -> float:
            if col not in df.columns:
                return 0.0
            vals = df.loc[df["mes"] == mes, col].dropna()
            return float(vals.mean()) if not vals.empty else 0.0

        previsoes: list[dict] = []
        prev_ndci: list[float] = []

        for h in range(1, horizonte_meses + 1):
            target_mes = (last_mes + h - 1) % 12 + 1
            target_ano = last_ano + (last_mes + h - 1) // 12

            if h == 1:
                nl1, nl2 = ndci_lag1_real, ndci_lag2_real
            elif h == 2:
                nl1, nl2 = prev_ndci[0], ndci_lag1_real
            else:
                nl1, nl2 = prev_ndci[h - 2], prev_ndci[h - 3]

            row = {
                "ndci_lag1":       nl1,
                "ndci_lag2":       nl2,
                "turbidez":        _last_val("turbidez"),
                "fai_mean":        _last_val("fai_mean"),
                "ndwi_mean":       _last_val("ndwi_mean"),
                "precip_total_mm": _mes_mean("precip_total_mm", target_mes),
                "chuva_lag1":      _last_val("chuva_lag1"),
                "chuva_acum2":     _last_val("chuva_acum2"),
                "lst_media_c":     _mes_mean("lst_media_c", target_mes),
                "lst_lag1":        _last_val("lst_lag1"),
                "mes_sin":         math.sin(2 * math.pi * target_mes / 12),
                "mes_cos":         math.cos(2 * math.pi * target_mes / 12),
            }

            X_row = np.array(
                [row.get(c, _last_val(c)) for c in self._feature_cols],
                dtype=float,
            )
            X_row = np.nan_to_num(X_row, nan=0.0).reshape(1, -1)

            pred_val = float(np.clip(
                self._model.predict(X_row)[0],
                _NDCI_CLIP_MIN, _NDCI_CLIP_MAX,
            ))

            # IC 80% via std das árvores individuais
            tree_preds = np.clip(
                np.array([t.predict(X_row)[0] for t in self._model.estimators_]),
                _NDCI_CLIP_MIN, _NDCI_CLIP_MAX,
            )
            sigma = float(tree_preds.std())
            inf80 = float(np.clip(pred_val - _Z80 * sigma, _NDCI_CLIP_MIN, _NDCI_CLIP_MAX))
            sup80 = float(np.clip(pred_val + _Z80 * sigma, _NDCI_CLIP_MIN, _NDCI_CLIP_MAX))

            prev_ndci.append(pred_val)

            previsoes.append({
                "ano_alvo":           target_ano,
                "mes_alvo":           target_mes,
                "horizonte_meses":    h,
                "valor_previsto":     round(pred_val, 6),
                "intervalo_inferior": round(inf80, 6),
                "intervalo_superior": round(sup80, 6),
            })

        return previsoes
