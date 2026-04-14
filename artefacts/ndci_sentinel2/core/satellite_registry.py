"""
Registry de satélites suportados pelo sistema.

Um SatelliteConfig descreve um satélite em termos de:
  - Coleção GEE
  - Mapeamento de bandas lógicas (B_RED, B_NIR, etc.) para nomes reais na coleção
  - Função de máscara de nuvens
  - Índices compatíveis
  - Ano de início da coleção

Adicionar suporte a um novo satélite = adicionar uma entrada no dict SATELLITES.

Exemplo: para adicionar Landsat-8:
    SATELLITES["landsat8"] = SatelliteConfig(
        key="landsat8",
        label="Landsat 8 OLI",
        collection="LANDSAT/LC08/C02/T1_L2",
        bands={
            "RED":      "SR_B4",
            "GREEN":    "SR_B3",
            "NIR":      "SR_B5",
        },
        cloud_mask_fn="landsat_qa",
        compatible_indices=["ndvi"],
        start_year=2013,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SatelliteConfig:
    """Metadados imutáveis de um satélite GEE."""

    key: str
    """Identificador curto, único — usado como chave no registry."""

    label: str
    """Nome legível (ex: 'Sentinel-2 SR Harmonizado')."""

    collection: str
    """ID da coleção no GEE (ex: 'COPERNICUS/S2_SR_HARMONIZED')."""

    bands: dict[str, str]
    """
    Mapeamento de nome lógico → nome real na coleção.
    Nomes lógicos reconhecidos: RED, GREEN, NIR, RED_EDGE_1, RED_EDGE_2,
    SWIR1, SWIR2, QA_PIXEL, SCL.
    """

    cloud_mask_fn: str
    """
    Nome da estratégia de máscara de nuvens.
    Valores reconhecidos: 'sentinel2_scl', 'landsat_qa'.
    O módulo `ingestion.<satellite>.cloud_mask` implementa cada estratégia.
    """

    compatible_indices: list[str] = field(default_factory=list)
    """Lista de chaves de índice (do index_registry) que este satélite suporta."""

    start_year: int = 2000
    """Ano de início da coleção (filtra tentativas de busca antes dos dados)."""

    scale_factor: float = 1.0
    """
    Fator de escala aplicado às bandas de reflectância antes do cálculo.
    Sentinel-2 SR: 0.0001 (valores brutos em [0, 10000]).
    Landsat C02 L2: 0.0000275 (com offset -0.2).
    """

    sr_offset: float = 0.0
    """Offset aditivo aplicado após o scale_factor (ver Landsat C02 L2)."""


# ── Registry ──────────────────────────────────────────────────────────────────

SATELLITES: dict[str, SatelliteConfig] = {
    "sentinel2": SatelliteConfig(
        key="sentinel2",
        label="Sentinel-2 MSI SR Harmonizado",
        collection="COPERNICUS/S2_SR_HARMONIZED",
        bands={
            "GREEN":      "B3",   # 560 nm, 10 m
            "RED":        "B4",   # 665 nm, 10 m (reamostrado para 20 m c/ B5)
            "RED_EDGE_1": "B5",   # 705 nm, 20 m  ← usado no NDCI
            "NIR":        "B8",   # 842 nm, 10 m
            "SCL":        "SCL",  # Scene Classification Layer
        },
        cloud_mask_fn="sentinel2_scl",
        compatible_indices=["ndci", "ndti", "ndwi"],
        start_year=2017,
        scale_factor=0.0001,  # reflectância em [0, 1]
        sr_offset=0.0,
    ),
}
