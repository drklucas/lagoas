"""
Pipeline de features para o modelo preditivo de NDCI.

Carrega dados de ndci_water_quality + tabelas externas de clima (GPM, LST)
e monta um DataFrame mensal com target = ndci_mean e features de lag + sazonalidade.

A dependência de dados climáticos (GPM/LST) é opcional: se as tabelas não
existirem no banco, as colunas de clima ficam NaN e o modelo usa apenas
as features internas (lags, sazonalidade, turbidez).
"""

from __future__ import annotations

import logging
import math

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import LAGOAS
from storage.database import engine

logger = logging.getLogger(__name__)

# Mapeamento lagoa → código IBGE do município de referência
# Usado para buscar dados climáticos GPM/LST
LAGOA_MUNICIPIO: dict[str, int] = {
    nome: cfg["municipio"] for nome, cfg in LAGOAS.items()
}


def _sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql_query(text(query), conn, params=params or {})


def load_ndci_features(
    lagoa: str,
    satellite: str = "sentinel2",
    db: Session | None = None,
) -> pd.DataFrame:
    """
    Carrega features mensais para previsão de NDCI em uma lagoa.

    Fontes:
      ndci_water_quality — ndci_mean (TARGET), ndti_mean, fai_mean, ndwi_mean, n_pixels
      gee_gpm            — precip_total_mm (se disponível no banco)
      gee_lst_mensal     — lst_media_c     (se disponível no banco)

    Returns:
        DataFrame indexado por data com colunas:
          ano, mes, target, turbidez, fai_mean, ndwi_mean,
          ndci_lag1, ndci_lag2,
          precip_total_mm, chuva_lag1, chuva_acum2,
          lst_media_c, lst_lag1,
          mes_sin, mes_cos
        Ou DataFrame vazio se não houver dados.
    """
    cod_ref = LAGOA_MUNICIPIO.get(lagoa)

    # ── Dados primários: ndci_water_quality ───────────────────────────────────
    agua = _sql("""
        SELECT
            ano, mes,
            ndci_mean   AS target,
            ndti_mean   AS turbidez,
            fai_mean,
            ndwi_mean,
            n_pixels
        FROM ndci_water_quality
        WHERE lagoa = :lagoa AND satellite = :satellite
        ORDER BY ano, mes
    """, {"lagoa": lagoa, "satellite": satellite})

    if agua.empty:
        logger.warning(
            "load_ndci_features: nenhum dado em ndci_water_quality para lagoa='%s'.", lagoa
        )
        return pd.DataFrame()

    agua["data"] = pd.to_datetime(
        agua["ano"].astype(str) + "-" + agua["mes"].astype(str).str.zfill(2) + "-01"
    )
    agua = agua.set_index("data").sort_index()

    # ── Dados climáticos externos (opcionais) ─────────────────────────────────
    if cod_ref is not None:
        try:
            clima = _sql("""
                SELECT
                    make_date(gp.ano::int, gp.mes::int, 1) AS data,
                    gp.precip_total_mm,
                    ls.lst_media_c
                FROM gee_gpm gp
                LEFT JOIN gee_lst_mensal ls
                       ON ls.cod_municipio = gp.cod_municipio
                      AND ls.ano = gp.ano
                      AND ls.mes = gp.mes
                WHERE gp.cod_municipio = :cod
                ORDER BY data
            """, {"cod": cod_ref})

            if not clima.empty:
                clima["data"] = pd.to_datetime(clima["data"])
                clima = clima.set_index("data")
                agua = agua.join(clima, how="left")
        except Exception as exc:
            logger.warning(
                "load_ndci_features: não foi possível carregar dados climáticos — %s. "
                "O modelo usará apenas features internas.", exc
            )

    # ── Features de lag ───────────────────────────────────────────────────────
    agua["ndci_lag1"] = agua["target"].shift(1)
    agua["ndci_lag2"] = agua["target"].shift(2)

    if "precip_total_mm" in agua.columns:
        agua["chuva_lag1"]  = agua["precip_total_mm"].shift(1)
        agua["chuva_acum2"] = agua["precip_total_mm"].shift(1).rolling(2).sum()
    else:
        agua["precip_total_mm"] = float("nan")
        agua["chuva_lag1"]      = float("nan")
        agua["chuva_acum2"]     = float("nan")

    if "lst_media_c" in agua.columns:
        agua["lst_lag1"] = agua["lst_media_c"].shift(1)
    else:
        agua["lst_media_c"] = float("nan")
        agua["lst_lag1"]    = float("nan")

    # ── Sazonalidade circular ─────────────────────────────────────────────────
    agua["mes_sin"] = [math.sin(2 * math.pi * m / 12) for m in agua.index.month]
    agua["mes_cos"] = [math.cos(2 * math.pi * m / 12) for m in agua.index.month]

    # Remove primeiras linhas que não têm ndci_lag2
    agua = agua.dropna(subset=["ndci_lag2"])

    return agua.reset_index()
