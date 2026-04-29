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
from dataclasses import dataclass, field

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
    n_outliers_removidos: int = 0
    outliers: list[dict] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    erro: str | None = None


def _sgn(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


_MONTH_NAMES = {
    1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
    7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez",
}


def _seasonal_outlier_filter(
    yvpairs: list[tuple[int, float]],
    z_threshold: float = 3.5,
) -> tuple[list[tuple[int, float]], list[tuple[int, float, float]]]:
    """
    Remove start-of-series initialization outliers using the modified z-score
    (Iglewicz & Hoaglin, 1993):

        M_i = 0.6745 × |x_i − median(x)| / MAD(x)

    The filter is intentionally narrow: it only flags observations from the
    FIRST calendar year in the season (yvpairs is sorted by year).  This
    targets the known bias where an anomalous value at the very beginning of
    the Sentinel-2 archive (e.g., Jul/Aug 2017) dominates the S statistic for
    that season while leaving legitimate bloom events in later years untouched.

    Only applied when n ≥ 5 (need reliable MAD estimate).
    Always keeps at least 3 observations per season.

    Returns (filtered_pairs, [(year, value, z_score), ...] of removed obs).
    """
    if len(yvpairs) < 5:
        return yvpairs, []

    vals = np.array([v for _, v in yvpairs])
    median = float(np.median(vals))
    mad = float(np.median(np.abs(vals - median)))

    if mad < 1e-10:
        return yvpairs, []

    # Only candidates from the first year of data in this season
    first_year = yvpairs[0][0]

    filtered: list[tuple[int, float]] = []
    removed:  list[tuple[int, float, float]] = []
    for y, v in yvpairs:
        m_i = 0.6745 * abs(v - median) / mad
        if y == first_year and m_i > z_threshold:
            removed.append((y, v, round(m_i, 2)))
        else:
            filtered.append((y, v))

    if len(filtered) < 3:
        return yvpairs, []

    return filtered, removed


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
    all_outliers: list[dict] = []

    for m, yvpairs in seasons.items():
        # Per-season outlier filter before computing S
        yvpairs, removed = _seasonal_outlier_filter(yvpairs)
        for y_r, v_r, z_r in removed:
            all_outliers.append({
                "mes": m, "ano": y_r,
                "valor": round(v_r, 6), "z_mod": z_r,
            })

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

    avisos: list[str] = []
    if all_outliers:
        by_mes: dict[int, list[dict]] = defaultdict(list)
        for o in all_outliers:
            by_mes[o["mes"]].append(o)
        for mes, obs in sorted(by_mes.items()):
            detalhes = ", ".join(
                f"{o['ano']} ({o['valor']:+.4f}, z={o['z_mod']})" for o in obs
            )
            avisos.append(
                f"{_MONTH_NAMES[mes].capitalize()}: {len(obs)} obs removida(s) — {detalhes}"
            )

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
        n_outliers_removidos=len(all_outliers),
        outliers=all_outliers,
        avisos=avisos,
        erro=None,
    )
