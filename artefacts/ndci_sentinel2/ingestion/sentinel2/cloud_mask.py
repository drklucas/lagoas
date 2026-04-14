"""
Máscara de nuvens para imagens Sentinel-2 via SCL (Scene Classification Layer).

A SCL é produzida pelo processador Sen2Cor e classifica cada pixel em:
  0  — NO_DATA
  1  — SATURATED_OR_DEFECTIVE
  2  — DARK_AREA_PIXELS
  3  — CLOUD_SHADOWS         ← removido
  4  — VEGETATION
  5  — NOT_VEGETATED
  6  — WATER
  7  — UNCLASSIFIED
  8  — CLOUD_MEDIUM_PROB     ← removido
  9  — CLOUD_HIGH_PROB       ← removido
  10 — THIN_CIRRUS           ← removido
  11 — SNOW_ICE

Mantemos apenas pixels classificados como WATER (6), que é o que nos interessa,
com a máscara de água adicional via NDWI > threshold aplicada depois.
Na prática, manter todos os pixels não-nuvem (não-3/8/9/10) é mais conservador
e equivalente ao comportamento do eyefish original.
"""

from __future__ import annotations


def cloud_mask_s2(img):
    """
    Aplica máscara SCL a uma imagem Sentinel-2.
    Remove: sombra de nuvem (3), nuvem média (8), nuvem alta (9), cirrus (10).
    Retorna a imagem com máscara aplicada.

    Esta função é projetada para ser passada diretamente ao ee.ImageCollection.map().
    """
    import ee as _ee

    scl  = img.select("SCL")
    mask = (
        scl.neq(3)
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
    )
    return img.updateMask(mask)
