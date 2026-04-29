"""
Two-sided CUSUM (Cumulative Sum) control chart for change-point detection.

Reference:
  Page, E.S. (1954). Continuous inspection schemes.
    Biometrika 41(1-2):100–115.

Parameters follow environmental monitoring conventions:
  k = 0.5 σ  — reference value (detects shifts ≥ 1σ efficiently)
  h = 4.0 σ  — decision interval (false-alarm rate ≈ 1/370 for Gaussian data)

Baseline estimator: median + MAD×1.4826 (robust to outliers at series start).
Monitoring phase starts only after the baseline period ends (no circular accumulation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class CUSUMAlarm:
    periodo: str              # "YYYY-MM" or "YYYY-MM-DD"
    tipo: str                 # "elevacao" | "queda"
    cusum_value: float        # CUSUM statistic at alarm
    data_inicio_shift: str    # estimated start of the regime shift


@dataclass
class CUSUMResult:
    baseline_mean: float
    baseline_std: float
    k: float                  # reference value in original units
    h: float                  # decision interval in original units
    k_fator: float
    h_fator: float
    n_baseline: int
    periodo_baseline: str
    alarmes: list[CUSUMAlarm]
    periodos: list[str]
    valores: list[float | None]
    cusum_pos: list[float]    # CUSUM⁺ (detects upward shifts)
    cusum_neg: list[float]    # CUSUM⁻ (detects downward shifts)
    n_obs: int
    # Robust baseline diagnostics
    aviso_baseline_contaminado: bool = False
    outliers_baseline: list[dict] = field(default_factory=list)
    baseline_estimador: str = "mediana/MAD"
    erro: str | None = None


def cusum_analysis(
    values: list[float | None],
    periodos: list[str],
    baseline_n: int | None = None,
    k_fator: float = 0.5,
    h_fator: float = 4.0,
) -> CUSUMResult:
    """
    Bidirectional CUSUM change-point analysis (Page, 1954).

    The CUSUM statistics are:
      C_t⁺ = max(0, C_{t-1}⁺ + (x_t − μ₀) − k)   detects upward shift
      C_t⁻ = max(0, C_{t-1}⁻ − (x_t − μ₀) − k)   detects downward shift

    An alarm fires when C_t⁺ > h or C_t⁻ > h.
    The estimated start of the shift is the time of the most recent reset
    (i.e., the last time the statistic touched zero before the alarm).

    Baseline parameters are estimated robustly via median and MAD×1.4826,
    which makes k and h resistant to extreme values at the start of the series.
    Monitoring (accumulation) begins only after the baseline period ends to
    avoid circular contamination.

    Args:
        values:      Time series (None / NaN = missing, kept in output series).
        periodos:    Period labels aligned with values.
        baseline_n:  Initial observations used to estimate μ₀ and σ.
                     Default: min(24, 30% of valid obs), minimum 5.
        k_fator:     k = k_fator × σ₀  (default 0.5).
        h_fator:     h = h_fator × σ₀  (default 4.0).

    Returns:
        CUSUMResult with alarm list, full CUSUM series, and baseline diagnostics.
    """
    valid_idx_val = [
        (i, float(v))
        for i, v in enumerate(values)
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    n_valid = len(valid_idx_val)

    if n_valid < 6:
        return CUSUMResult(
            baseline_mean=0.0,
            baseline_std=1.0,
            k=0.0,
            h=float("inf"),
            k_fator=k_fator,
            h_fator=h_fator,
            n_baseline=0,
            periodo_baseline="",
            alarmes=[],
            periodos=periodos,
            valores=list(values),
            cusum_pos=[0.0] * len(values),
            cusum_neg=[0.0] * len(values),
            n_obs=n_valid,
            erro="Dados insuficientes para CUSUM (mínimo 6 observações válidas)",
        )

    # Baseline length: at least 5, at most 24 valid observations
    if baseline_n is None:
        baseline_n = max(5, min(24, int(n_valid * 0.30)))
    baseline_n = min(baseline_n, n_valid - 3)

    baseline_pairs = valid_idx_val[:baseline_n]
    baseline_arr   = np.array([v for _, v in baseline_pairs])

    # ── Robust baseline estimator: median + MAD×1.4826 ───────────────────────
    # 1.4826 = 1/Φ⁻¹(0.75) — makes MAD a consistent estimator of σ (Hampel, 1974)
    mu0 = float(np.median(baseline_arr))
    mad = float(np.median(np.abs(baseline_arr - mu0)))
    sigma = mad * 1.4826
    if sigma < 1e-10:
        sigma = max(1e-4, abs(mu0) * 0.01)

    k = k_fator * sigma
    h = h_fator * sigma

    bl_start = periodos[baseline_pairs[0][0]]
    bl_end   = periodos[baseline_pairs[-1][0]]
    periodo_baseline = f"{bl_start} a {bl_end}"

    # ── Baseline contamination check (modified z-score, Iglewicz & Hoaglin 1993)
    # M_i = 0.6745 × |x_i − median| / MAD; flag if |M_i| > 3.5
    outliers_baseline: list[dict] = []
    if mad > 1e-10:
        for orig_idx, v in baseline_pairs:
            m_i = 0.6745 * abs(v - mu0) / mad
            if m_i > 3.5:
                outliers_baseline.append({
                    "periodo": periodos[orig_idx],
                    "valor":   round(v, 6),
                    "z_mod":   round(m_i, 2),
                })

    # Index in the original `values` array of the last baseline observation
    last_baseline_idx = baseline_pairs[-1][0]

    # ── Run CUSUM — monitoring starts after baseline ──────────────────────────
    cp_pos = 0.0
    cp_neg = 0.0
    # Initialise reset markers at last baseline position so shift-start
    # estimates correctly anchor to the start of the monitoring window.
    last_reset_pos: int = last_baseline_idx
    last_reset_neg: int = last_baseline_idx
    in_alarm_pos = False
    in_alarm_neg = False

    cusum_pos: list[float] = []
    cusum_neg: list[float] = []
    alarmes: list[CUSUMAlarm] = []

    for i, v in enumerate(values):
        # Baseline period — output zero, no accumulation
        if i <= last_baseline_idx:
            cusum_pos.append(0.0)
            cusum_neg.append(0.0)
            continue

        if v is None or (isinstance(v, float) and math.isnan(v)):
            cusum_pos.append(round(cp_pos, 8))
            cusum_neg.append(round(cp_neg, 8))
            continue

        fv = float(v)
        cp_pos = max(0.0, cp_pos + (fv - mu0) - k)
        cp_neg = max(0.0, cp_neg - (fv - mu0) - k)

        # Track resets (C returns to zero → shift ended / new baseline phase)
        if cp_pos == 0.0:
            last_reset_pos = i
            in_alarm_pos = False
        if cp_neg == 0.0:
            last_reset_neg = i
            in_alarm_neg = False

        cusum_pos.append(round(cp_pos, 8))
        cusum_neg.append(round(cp_neg, 8))

        if cp_pos > h and not in_alarm_pos:
            in_alarm_pos = True
            shift_idx = min(last_reset_pos + 1, i)
            alarmes.append(CUSUMAlarm(
                periodo=periodos[i],
                tipo="elevacao",
                cusum_value=round(cp_pos, 6),
                data_inicio_shift=periodos[shift_idx],
            ))

        if cp_neg > h and not in_alarm_neg:
            in_alarm_neg = True
            shift_idx = min(last_reset_neg + 1, i)
            alarmes.append(CUSUMAlarm(
                periodo=periodos[i],
                tipo="queda",
                cusum_value=round(cp_neg, 6),
                data_inicio_shift=periodos[shift_idx],
            ))

    clean_vals: list[float | None] = [
        round(float(v), 6) if v is not None else None
        for v in values
    ]

    return CUSUMResult(
        baseline_mean=round(mu0, 6),
        baseline_std=round(sigma, 6),
        k=round(k, 6),
        h=round(h, 6),
        k_fator=k_fator,
        h_fator=h_fator,
        n_baseline=baseline_n,
        periodo_baseline=periodo_baseline,
        alarmes=alarmes,
        periodos=periodos,
        valores=clean_vals,
        cusum_pos=cusum_pos,
        cusum_neg=cusum_neg,
        n_obs=n_valid,
        aviso_baseline_contaminado=len(outliers_baseline) > 0,
        outliers_baseline=outliers_baseline,
        baseline_estimador="mediana/MAD",
        erro=None,
    )
