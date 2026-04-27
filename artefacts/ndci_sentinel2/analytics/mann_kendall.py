"""
Seasonal Mann-Kendall trend test with Sen's slope estimator.

References:
  Mann, H.B. (1945). Nonparametric tests against trend. Econometrica 13:245–259.
  Kendall, M.G. (1975). Rank Correlation Methods. Griffin, London.
  Hirsch, R.M., Slack, J.R., Smith, R.A. (1982). Techniques of trend analysis
    for monthly water quality data. Water Resour. Res. 18(1):107–121.
  Hamed, K.H., Rao, A.R. (1998). A modified Mann-Kendall trend test for
    autocorrelated data. J. Hydrol. 204:182–196.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np


@dataclass
class MKResult:
    trend: str                # "crescente" | "decrescente" | "sem_tendencia"
    significativo: bool       # p < alpha
    p_value: float
    z_score: float
    s_stat: float             # Mann-Kendall S statistic
    tau: float                # Kendall tau (approximation)
    sen_slope_mes: float      # Sen's slope in index units / month
    sen_slope_ano: float      # Sen's slope in index units / year
    n_obs: int                # total valid observations used
    n_seasons_com_dados: int  # distinct months (seasons) with ≥2 obs
    periodo_inicio: str       # "YYYY-MM"
    periodo_fim: str          # "YYYY-MM"
    alpha: float
    erro: str | None = None


def _sgn(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _var_s_season(n: int, vals: list[float]) -> float:
    """
    Variance of S for one season (month), including tie correction.

    V(S) = [n(n-1)(2n+5) - Σ_p t_p(t_p-1)(2t_p+5)] / 18
    """
    base = n * (n - 1) * (2 * n + 5)
    tie_correction = sum(
        t * (t - 1) * (2 * t + 5)
        for t in Counter(vals).values()
        if t > 1
    )
    return (base - tie_correction) / 18.0


def seasonal_mann_kendall(
    values: list[float | None],
    months: list[int],
    years: list[int],
    alpha: float = 0.05,
) -> MKResult:
    """
    Seasonal Mann-Kendall test (Hirsch et al., 1982).

    Groups observations by calendar month (season) before computing S,
    which removes the annual cycle and focuses on inter-annual trend.

    Args:
        values: Index values; None or NaN entries are skipped.
        months: Calendar month for each observation (1–12).
        years:  Calendar year for each observation.
        alpha:  Significance level (default 0.05).

    Returns:
        MKResult with test statistics, Sen's slope, and interpretation.
    """
    triples = [
        (y, m, v)
        for y, m, v in zip(years, months, values)
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]

    if len(triples) < 4:
        return MKResult(
            trend="sem_tendencia",
            significativo=False,
            p_value=1.0,
            z_score=0.0,
            s_stat=0.0,
            tau=0.0,
            sen_slope_mes=0.0,
            sen_slope_ano=0.0,
            n_obs=len(triples),
            n_seasons_com_dados=0,
            periodo_inicio="",
            periodo_fim="",
            alpha=alpha,
            erro="Dados insuficientes (mínimo 4 observações)",
        )

    # Group by month (season), sort within each season by year
    seasons: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for y, m, v in triples:
        seasons[m].append((y, float(v)))
    for m in seasons:
        seasons[m].sort(key=lambda x: x[0])

    S_total = 0.0
    VarS_total = 0.0
    all_slopes: list[float] = []   # Sen's slope candidates (units/year)
    n_seasons_valid = 0

    for m, yvpairs in seasons.items():
        n_s = len(yvpairs)
        if n_s < 2:
            continue
        n_seasons_valid += 1

        ys = [p[0] for p in yvpairs]
        vs = [p[1] for p in yvpairs]

        # S for this season
        S_m = sum(
            _sgn(vs[k] - vs[j])
            for j in range(n_s - 1)
            for k in range(j + 1, n_s)
        )

        # Within-season Sen's slope candidates (units / year)
        for j in range(n_s - 1):
            for k in range(j + 1, n_s):
                dy = ys[k] - ys[j]
                if dy > 0:
                    all_slopes.append((vs[k] - vs[j]) / dy)

        S_total += S_m
        VarS_total += _var_s_season(n_s, vs)

    # Z statistic (continuity-corrected)
    if VarS_total <= 0:
        z = 0.0
    elif S_total > 0:
        z = (S_total - 1.0) / math.sqrt(VarS_total)
    elif S_total < 0:
        z = (S_total + 1.0) / math.sqrt(VarS_total)
    else:
        z = 0.0

    # Two-tailed p-value via complementary error function (no scipy dependency)
    p = math.erfc(abs(z) / math.sqrt(2))

    # Sen's slope
    if all_slopes:
        sen_ano = float(np.median(all_slopes))
        sen_mes = sen_ano / 12.0
    else:
        sen_ano = 0.0
        sen_mes = 0.0

    # Approximate Kendall tau
    n_total = len(triples)
    tau = S_total / (0.5 * n_total * (n_total - 1)) if n_total > 1 else 0.0

    sig = p < alpha
    if sig:
        trend = "crescente" if z > 0 else "decrescente"
    else:
        trend = "sem_tendencia"

    all_sorted = sorted((y, m) for y, m, _ in triples)
    inicio = f"{all_sorted[0][0]}-{all_sorted[0][1]:02d}"
    fim    = f"{all_sorted[-1][0]}-{all_sorted[-1][1]:02d}"

    return MKResult(
        trend=trend,
        significativo=sig,
        p_value=round(p, 6),
        z_score=round(z, 4),
        s_stat=round(S_total, 2),
        tau=round(tau, 4),
        sen_slope_mes=round(sen_mes, 8),
        sen_slope_ano=round(sen_ano, 6),
        n_obs=n_total,
        n_seasons_com_dados=n_seasons_valid,
        periodo_inicio=inicio,
        periodo_fim=fim,
        alpha=alpha,
        erro=None,
    )
