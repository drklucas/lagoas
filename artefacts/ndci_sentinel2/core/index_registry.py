"""
Registry de índices espectrais suportados pelo sistema.

Um IndexConfig descreve um índice em termos de:
  - Fórmula (quais bandas lógicas usa)
  - Parâmetros de visualização padrão
  - Thresholds de alerta (opcional)
  - Tipo de dado esperado (water, land, etc.)

Adicionar um novo índice = adicionar uma entrada em INDICES.

Exemplo: para adicionar NDVI:
    INDICES["ndvi"] = IndexConfig(
        key="ndvi",
        label="NDVI",
        description="Normalized Difference Vegetation Index",
        bands=("NIR", "RED"),
        formula="(NIR - RED) / (NIR + RED)",
        domain="land",
        vis_params={"min": -0.1, "max": 0.9, "palette": [...]},
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class AlertThreshold:
    """Define um nível de alerta para um valor de índice."""
    upper_bound: float   # exclusive — valor abaixo deste limite → este status
    status: str
    description: str


@dataclass(frozen=True)
class IndexConfig:
    """Metadados imutáveis de um índice espectral."""

    key: str
    """Identificador curto, único."""

    label: str
    """Nome legível (ex: 'NDCI')."""

    description: str
    """Descrição do que o índice mede."""

    bands: tuple[str, ...]
    """
    Bandas lógicas necessárias, na ordem em que a fórmula as usa.
    Estes são nomes lógicos que devem existir no SatelliteConfig.bands
    do satélite que calcula este índice.
    """

    formula: str
    """
    Expressão legível da fórmula (documentação / logs).
    Ex: '(RED_EDGE_1 - RED) / (RED_EDGE_1 + RED)'
    """

    domain: str
    """
    Domínio de aplicação: 'water' (lagoas/rios) ou 'land' (vegetação/solo).
    Workers de tiles de lagoa filtram apenas índices de domínio 'water'.
    """

    vis_params: dict
    """Parâmetros GEE getMapId(): min, max, palette."""

    alert_thresholds: tuple[AlertThreshold, ...] = field(default_factory=tuple)
    """
    Níveis de alerta em ordem crescente de severidade.
    O último threshold deve ter upper_bound=inf para capturar o pior caso.
    """

    result_range: tuple[float, float] = (-1.0, 1.0)
    """Faixa teórica do índice — usada para clip de segurança no ML."""


def _make_ndci_thresholds() -> tuple[AlertThreshold, ...]:
    return (
        AlertThreshold(0.02,          "bom",      "Águas claras, sem bloom"),
        AlertThreshold(0.10,          "moderado", "Presença moderada de algas"),
        AlertThreshold(0.20,          "elevado",  "Floração em desenvolvimento"),
        AlertThreshold(float("inf"),  "critico",  "Floração intensa — risco à saúde"),
    )


# ── Registry ──────────────────────────────────────────────────────────────────

INDICES: dict[str, IndexConfig] = {
    "ndci": IndexConfig(
        key="ndci",
        label="NDCI",
        description=(
            "Normalized Difference Chlorophyll Index — proxy de concentração "
            "de clorofila-a e cianobactérias em corpos d'água."
        ),
        bands=("RED_EDGE_1", "RED"),
        formula="(RED_EDGE_1 - RED) / (RED_EDGE_1 + RED)",
        domain="water",
        vis_params={
            "min": -0.1,
            "max":  0.30,
            "palette": [
                "000080",   # água limpa (NDCI negativo) — azul-marinho
                "0000FF",
                "00AAFF",
                "00FFFF",
                "00FF00",   # início de bloom — verde
                "FFFF00",
                "FF8000",
                "FF0000",   # bloom intenso (NDCI > 0.3) — vermelho
            ],
        },
        alert_thresholds=_make_ndci_thresholds(),
        result_range=(-1.0, 1.0),
    ),
    "ndti": IndexConfig(
        key="ndti",
        label="NDTI",
        description=(
            "Normalized Difference Turbidity Index — proxy de turbidez "
            "(partículas em suspensão) em corpos d'água."
        ),
        bands=("RED", "GREEN"),
        formula="(RED - GREEN) / (RED + GREEN)",
        domain="water",
        vis_params={
            "min": -0.30,
            "max":  0.30,
            "palette": [
                "000080",   # água muito clara
                "4169E1",
                "87CEEB",
                "F0E68C",   # turbidez moderada
                "DEB887",
                "8B4513",   # água muito turva
            ],
        },
        result_range=(-1.0, 1.0),
    ),
    "ndwi": IndexConfig(
        key="ndwi",
        label="NDWI",
        description=(
            "Normalized Difference Water Index — disponibilidade hídrica. "
            "Usado principalmente como máscara de água (pixels com NDWI ≤ -0.1 = terra)."
        ),
        bands=("GREEN", "NIR"),
        formula="(GREEN - NIR) / (GREEN + NIR)",
        domain="water",
        vis_params={
            "min": -0.5,
            "max":  0.5,
            "palette": ["8B4513", "DEB887", "87CEEB", "0000FF", "000080"],
        },
        result_range=(-1.0, 1.0),
    ),
}


def classify(index_key: str, value: float | None) -> str:
    """
    Classifica um valor de índice retornando o status de alerta correspondente.
    Retorna 'sem_dados' se value for None ou o índice não tiver thresholds.
    """
    if value is None:
        return "sem_dados"
    cfg = INDICES.get(index_key)
    if cfg is None or not cfg.alert_thresholds:
        return "sem_dados"
    for threshold in cfg.alert_thresholds:
        if value < threshold.upper_bound:
            return threshold.status
    return cfg.alert_thresholds[-1].status
