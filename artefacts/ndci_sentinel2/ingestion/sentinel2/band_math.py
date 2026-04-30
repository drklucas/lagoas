"""
Cálculo de índices espectrais a partir de imagens Sentinel-2.

Todos os índices são adicionados como bandas extras à imagem original via
addBands(), seguindo o padrão GEE de pipelines funcionais.

Índices calculados:
  NDCI  = (B5 - B4) / (B5 + B4)   — clorofila / cianobactérias
  NDTI  = (B4 - B3) / (B4 + B3)   — turbidez
  NDWI  = (B3 - B8) / (B3 + B8)   — máscara de água / disponibilidade hídrica
  FAI   = B8 - (B4 + (B11 - B4) × (842 - 665) / (1610 - 665))
          — Floating Algae Index (material flutuante na superfície)

A máscara de água usa NDWI > threshold OR FAI > 0 para incluir pixels de
bloom denso de cianobactérias que têm alta reflectância no NIR e podem ter
NDWI levemente negativo (abaixo do threshold). O buffer negativo de borda
(configurado por lagoa em config.py) evita que pixels de terra entrem pela
extensão do threshold.

Threshold padrão: -0.2 (relaxado de -0.1 para reter pixels de bloom).
Referência: Pi & Guasselli (SBSR 2025).
"""

from __future__ import annotations


def add_water_indices(img):
    """
    Adiciona NDCI, NDTI, NDWI e FAI como bandas à imagem Sentinel-2.

    Projetado para uso em ee.ImageCollection.map().

    Bandas utilizadas:
      B3  — Verde    560 nm  10 m
      B4  — Vermelho 665 nm  10 m
      B5  — Red-Edge 705 nm  20 m  ← sensível à reflectância de clorofila
      B8  — NIR      842 nm  10 m
      B11 — SWIR1   1610 nm  20 m  ← usado para FAI
    """
    b3  = img.select("B3").toFloat()
    b4  = img.select("B4").toFloat()
    b5  = img.select("B5").toFloat()
    b8  = img.select("B8").toFloat()
    b11 = img.select("B11").toFloat()

    ndci = b5.subtract(b4).divide(b5.add(b4)).rename("NDCI")
    ndti = b4.subtract(b3).divide(b4.add(b3)).rename("NDTI")
    ndwi = b3.subtract(b8).divide(b3.add(b8)).rename("NDWI")

    # FAI: interpolação linear na linha de base NIR entre B4 (665 nm) e B11 (1610 nm)
    nir_baseline = b4.add(
        b11.subtract(b4).multiply((842 - 665) / (1610 - 665))
    )
    fai = b8.subtract(nir_baseline).rename("FAI")

    ndvi = b8.subtract(b4).divide(b8.add(b4)).rename("NDVI")

    return img.addBands([ndci, ndti, ndwi, fai, ndvi])


def water_mask(composite, threshold: float = -0.2):
    """
    Cria máscara de água combinando NDWI e FAI.

    Lógica: pixels com (NDWI > threshold) OR (FAI > 0) são considerados água.

    O critério FAI > 0 retém pixels de bloom denso de cianobactérias que
    têm alta reflectância no NIR e podem ter NDWI abaixo do threshold.
    O buffer negativo por lagoa (config.py) limita a inclusão de pixels
    de borda/terra quando o threshold é relaxado.

    Args:
        composite: ee.Image já com bandas NDWI e FAI (via add_water_indices).
        threshold: corte NDWI (default: -0.2, relaxado de -0.1).
    """
    ndwi_mask = composite.select("NDWI").gt(threshold)
    fai_mask  = composite.select("FAI").gt(0)
    return composite.updateMask(ndwi_mask.Or(fai_mask))


def land_mask(composite):
    """
    Retém apenas pixels de terra (NDWI < 0).

    Usado pelo worker de NDVI para excluir água residual do anel de vegetação.
    O anel já inicia fora da lagoa (buffer positivo), então a máscara é apenas
    uma salvaguarda contra canais, banhados e pixels mistos na borda interna.
    """
    return composite.updateMask(composite.select("NDWI").lt(0))
