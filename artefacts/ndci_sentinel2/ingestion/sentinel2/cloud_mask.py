"""
Máscara de nuvens para imagens Sentinel-2 via SCL (Scene Classification Layer).

A SCL é produzida pelo processador Sen2Cor e classifica cada pixel em:
  0  — NO_DATA
  1  — SATURATED_OR_DEFECTIVE    ← removido
  2  — DARK_AREA_PIXELS
  3  — CLOUD_SHADOWS             ← removido
  4  — VEGETATION                  mantido — bloom denso de cianobactérias é
                                   classificado como VEGETATION pelo Sen2Cor
  5  — NOT_VEGETATED
  6  — WATER
  7  — UNCLASSIFIED
  8  — CLOUD_MEDIUM_PROB         ← removido
  9  — CLOUD_HIGH_PROB           ← removido
  10 — THIN_CIRRUS               ← removido
  11 — SNOW_ICE

A classe 4 (VEGETATION) é mantida deliberadamente: florescências densas de
cianobactérias têm espectro semelhante à vegetação rasteira e são classificadas
como classe 4 pelo Sen2Cor. Removê-la descartaria exatamente os pixels com
NDCI mais alto, introduzindo viés sistemático negativo.

Referência: Pi & Guasselli (SBSR 2025); Mishra & Mishra (2012).
"""

from __future__ import annotations


def cloud_mask_s2(img):
    """
    Aplica máscara SCL a uma imagem Sentinel-2.

    Remove:
      - classe 1  — pixel saturado/defeituoso
      - classe 3  — sombra de nuvem
      - classe 8  — nuvem probabilidade média
      - classe 9  — nuvem probabilidade alta
      - classe 10 — cirrus fino

    Mantém explicitamente:
      - classe 4 (VEGETATION) — bloom de cianobactérias misturado com sinal vegetal

    Projetada para uso em ee.ImageCollection.map().
    """
    import ee as _ee

    scl  = img.select("SCL")
    mask = (
        scl.neq(1)    # saturado/defeituoso
        .And(scl.neq(3))    # sombra de nuvem
        .And(scl.neq(8))    # nuvem média prob
        .And(scl.neq(9))    # nuvem alta prob
        .And(scl.neq(10))   # cirrus
    )
    return img.updateMask(mask)
