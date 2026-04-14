"""Core — abstrações puras de satélites e índices (sem dependências de DB ou GEE)."""
from .satellite_registry import SATELLITES, SatelliteConfig
from .index_registry import INDICES, IndexConfig, classify

__all__ = ["SATELLITES", "SatelliteConfig", "INDICES", "IndexConfig", "classify"]
