"""Módulo ML — features e predictor NDCI."""
from .features import load_ndci_features, LAGOA_MUNICIPIO
from .predictor import NdciPredictor

__all__ = ["load_ndci_features", "LAGOA_MUNICIPIO", "NdciPredictor"]
