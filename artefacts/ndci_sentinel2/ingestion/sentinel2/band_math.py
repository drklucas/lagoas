"""
Cálculo de índices espectrais a partir de imagens Sentinel-2.

Todos os índices são adicionados como bandas extras à imagem original via
addBands(), seguindo o padrão GEE de pipelines funcionais.

Índices calculados:
  NDCI  = (B5 - B4) / (B5 + B4)   — clorofila / cianobactérias
  NDTI  = (B4 - B3) / (B4 + B3)   — turbidez
  NDWI  = (B3 - B8) / (B3 + B8)   — máscara de água / disponibilidade hídrica

Por que usar toFloat()?
  As bandas do Sentinel-2 SR são armazenadas como Int16 no GEE.
  A divisão inteira produziria resultados incorretos (truncados para 0 ou -1).
  toFloat() garante divisão de ponto flutuante antes do cálculo.
"""

from __future__ import annotations


def add_water_indices(img):
    """
    Adiciona NDCI, NDTI e NDWI como bandas à imagem Sentinel-2.

    Projetado para uso em ee.ImageCollection.map().

    Bandas utilizadas:
      B3 — Verde  560 nm  10 m
      B4 — Vermelho 665 nm  10 m  (reamostrado para 20 m com B5)
      B5 — Red-Edge 705 nm  20 m  ← sensível à reflectância de clorofila
      B8 — NIR    842 nm  10 m
    """
    b3 = img.select("B3").toFloat()
    b4 = img.select("B4").toFloat()
    b5 = img.select("B5").toFloat()
    b8 = img.select("B8").toFloat()

    ndci = b5.subtract(b4).divide(b5.add(b4)).rename("NDCI")
    ndti = b4.subtract(b3).divide(b4.add(b3)).rename("NDTI")
    ndwi = b3.subtract(b8).divide(b3.add(b8)).rename("NDWI")

    return img.addBands([ndci, ndti, ndwi])


def water_mask(composite, threshold: float = -0.1):
    """
    Cria máscara de água a partir de uma imagem composta.

    Pixels com NDWI <= threshold são considerados terra e descartados.
    Retorna a imagem composta com apenas pixels de água visíveis.

    Args:
        composite: ee.Image já com banda NDWI calculada (via add_water_indices).
        threshold: valor de corte NDWI (default: -0.1, conforme eyefish).
    """
    mask = composite.select("NDWI").gt(threshold)
    return composite.updateMask(mask)
