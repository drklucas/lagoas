"""
Configuração central do sistema NDCI/Sentinel-2.

Lagoas, polígonos GEE, bounding boxes e parâmetros de visualização ficam
aqui — um único ponto de mudança para adicionar novas lagoas ou ajustar
paletas de cores.
"""

from __future__ import annotations

# ── TTL dos tiles GEE ─────────────────────────────────────────────────────────
# Map IDs expiram empiricamente em ~24 h. Usamos 23 h para garantir margem.
TILE_TTL_HOURS: int = 23

# Janela de antecedência para o worker de refresh (regenera antes de expirar)
TILE_REFRESH_WINDOW_HOURS: int = 6

# ── Lagoas monitoradas ────────────────────────────────────────────────────────
#
# Cada entrada define:
#   polygon   — lista de [lon, lat] em sentido horário (aceito pelo GEE Polygon)
#   bbox      — [west, south, east, north] para o frontend / fitBounds
#   municipio — código IBGE do município de referência (usado para GPM/LST)
#
# NOTA: O eyefish original separava as lagoas de tiles visuais (Peixoto, Barros)
# das lagoas de dados numéricos/ML (Tramandaí, Armazém, Itapeva, Quadros).
# Aqui unificamos as 6 lagoas em um único registro. Cada lagoa expõe ambas
# as capacidades (tiles + stats) conforme disponibilidade de polígono.

LAGOAS: dict[str, dict] = {
    # ── Lagoas com polígono preciso para tiles visuais ──────────────────────
    "Lagoa do Peixoto": {
        "polygon": [
            [-50.248506, -29.869936],
            [-50.241872, -29.869051],
            [-50.242280, -29.860022],
            [-50.236564, -29.857366],
            [-50.231052, -29.861969],
            [-50.231052, -29.868254],
            [-50.233910, -29.874007],
            [-50.236870, -29.883035],
            [-50.243913, -29.881176],
            [-50.249629, -29.874804],
            [-50.247588, -29.869493],
            [-50.248506, -29.869936],
        ],
        "bbox": [-50.252, -29.886, -50.229, -29.855],
        "municipio": 4313508,   # Osório
    },
    "Lagoa dos Barros": {
        "polygon": [
            [-50.418768, -29.936907],
            [-50.424838, -29.876300],
            [-50.402746, -29.866406],
            [-50.373857, -29.891876],
            [-50.327974, -29.896927],
            [-50.319477, -29.901347],
            [-50.318992, -29.923021],
            [-50.353950, -29.986122],
            [-50.375799, -29.989486],
            [-50.410514, -29.954997],
            [-50.426051, -29.897559],
            [-50.418768, -29.936907],
        ],
        "bbox": [-50.430, -29.992, -50.315, -29.860],
        "municipio": 4313508,   # Osório
    },
    # ── Lagoas usadas para dados numéricos/ML (bbox aproximada) ─────────────
    # Polígono derivado do bbox — pode ser refinado com coordenadas precisas.
    "Lagoa de Tramandaí": {
        "polygon": [
            [-50.140, -29.990],
            [-50.100, -29.990],
            [-50.100, -29.960],
            [-50.140, -29.960],
            [-50.140, -29.990],
        ],
        "bbox": [-50.140, -29.990, -50.100, -29.960],
        "municipio": 4321600,   # Tramandaí
    },
    "Lagoa do Armazém": {
        "polygon": [
            [-50.155, -29.975],
            [-50.125, -29.975],
            [-50.125, -29.955],
            [-50.155, -29.955],
            [-50.155, -29.975],
        ],
        "bbox": [-50.155, -29.975, -50.125, -29.955],
        "municipio": 4321600,   # Tramandaí
    },
    "Lagoa Itapeva": {
        "polygon": [
            [-50.010, -29.400],
            [-49.980, -29.400],
            [-49.980, -29.330],
            [-50.010, -29.330],
            [-50.010, -29.400],
        ],
        "bbox": [-50.010, -29.400, -49.980, -29.330],
        "municipio": 4321501,   # Torres
    },
    "Lagoa dos Quadros": {
        "polygon": [
            [-50.210, -29.780],
            [-50.140, -29.780],
            [-50.140, -29.720],
            [-50.210, -29.720],
            [-50.210, -29.780],
        ],
        "bbox": [-50.210, -29.780, -50.140, -29.720],
        "municipio": 4313508,   # Osório
    },
    "Lagoa Caconde": {
        "polygon": [
            [-50.221928, -29.866105],
            [-50.221682, -29.866961],
            [-50.219703, -29.870376],
            [-50.218962, -29.870969],
            [-50.217781, -29.872646],
            [-50.216207, -29.873253],
            [-50.215489, -29.870359],
            [-50.212515, -29.869984],
            [-50.212198, -29.867433],
            [-50.210410, -29.866127],
            [-50.207980, -29.866457],
            [-50.208158, -29.867915],
            [-50.207717, -29.870461],
            [-50.206379, -29.872133],
            [-50.205469, -29.872512],
            [-50.203971, -29.875232],
            [-50.200542, -29.875817],
            [-50.199414, -29.876641],
            [-50.198473, -29.876806],
            [-50.196738, -29.875518],
            [-50.196404, -29.873596],
            [-50.195722, -29.872432],
            [-50.195869, -29.871246],
            [-50.194950, -29.869694],
            [-50.195035, -29.869008],
            [-50.194424, -29.865275],
            [-50.195338, -29.861864],
            [-50.196301, -29.861984],
            [-50.197300, -29.860910],
            [-50.199342, -29.860326],
            [-50.200181, -29.861373],
            [-50.201126, -29.861128],
            [-50.201795, -29.860294],
            [-50.205848, -29.860540],
            [-50.206793, -29.860905],
            [-50.208376, -29.860709],
            [-50.210615, -29.861431],
            [-50.213072, -29.861650],
            [-50.214213, -29.862484],
            [-50.214824, -29.862194],
            [-50.215449, -29.861418],
            [-50.216474, -29.862020],
            [-50.217683, -29.861868],
            [-50.219738, -29.864152],
            [-50.219983, -29.864736],
            [-50.221928, -29.866105],
        ],
        "bbox": [-50.222, -29.877, -50.194, -29.860],
        "municipio": 4313508,   # Osório
    },
}

# ── Paletas de visualização NDCI ──────────────────────────────────────────────

NDCI_VIS_PARAMS: dict = {
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
}

TURBIDEZ_VIS_PARAMS: dict = {
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
}

# ── Escala de alerta NDCI ─────────────────────────────────────────────────────

NDCI_ALERT_THRESHOLDS: list[tuple[float, str, str]] = [
    # (limite_superior, status, descricao)
    (0.02,  "bom",      "Águas claras, sem bloom"),
    (0.10,  "moderado", "Presença moderada de algas"),
    (0.20,  "elevado",  "Floração em desenvolvimento"),
    (float("inf"), "critico", "Floração intensa — risco à saúde"),
]


def classify_ndci(value: float | None) -> str:
    """Retorna o status de alerta para um valor de NDCI."""
    if value is None:
        return "sem_dados"
    for threshold, status, _ in NDCI_ALERT_THRESHOLDS:
        if value < threshold:
            return status
    return "critico"


# ── Parâmetros da máscara de água ─────────────────────────────────────────────
# Pixels com NDWI <= WATER_MASK_THRESHOLD são descartados (considerados terra).
WATER_MASK_THRESHOLD: float = -0.1

# ── Ano de início da coleção Sentinel-2 SR ───────────────────────────────────
SENTINEL2_START_YEAR: int = 2017
