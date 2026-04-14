"""
Modelos SQLAlchemy standalone para o sistema NDCI/Sentinel-2.

Dois modelos principais, espelhando a arquitetura de duas camadas do eyefish:
  - WaterQualityRecord  → estatísticas agregadas por lagoa/mês (série temporal + ML)
  - MapTileRecord       → URLs de tiles XYZ para visualização no mapa

A separação satélite/índice é refletida nas colunas `satellite` e `index_key`,
permitindo que a mesma tabela armazene dados de múltiplos satélites e índices
no futuro sem necessitar de nova migração.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    UniqueConstraint,
)

from storage.database import Base


class WaterQualityRecord(Base):
    """
    Estatísticas mensais de qualidade da água por lagoa, derivadas de
    imagens de satélite via Google Earth Engine (reduceRegion).

    Camada de dados numéricos — alimenta a API de série temporal e o modelo ML.

    Colunas de índice:
      ndci_mean   — NDCI médio no mês (proxy clorofila-a / cianobactérias)
      ndci_p90    — percentil 90 (pior pixel do mês)
      ndti_mean   — NDTI médio (turbidez / partículas em suspensão)
      fai_mean    — Floating Algae Index médio
      ndwi_mean   — NDWI médio (disponibilidade hídrica / máscara d'água)
      n_pixels    — pixels válidos usados no cálculo (sem nuvem, dentro da lagoa)

    Quanto maior o n_pixels, mais confiável o valor. Meses com alta cobertura
    de nuvens podem ter n_pixels muito baixo — use isso para filtrar dados ruins.
    """

    __tablename__ = "ndci_water_quality"

    id          = Column(Integer,      primary_key=True, autoincrement=True)
    satellite   = Column(String(50),   nullable=False, index=True)   # ex: "sentinel2"
    lagoa       = Column(String(100),  nullable=False, index=True)
    ano         = Column(SmallInteger, nullable=False)
    mes         = Column(SmallInteger, nullable=False)               # 1..12

    # Índices calculados
    ndci_mean   = Column(Float, nullable=True)   # NDCI médio — TARGET do ML
    ndci_p90    = Column(Float, nullable=True)   # percentil 90 (pior pixel)
    ndti_mean   = Column(Float, nullable=True)   # turbidez
    fai_mean    = Column(Float, nullable=True)   # Floating Algae Index
    ndwi_mean   = Column(Float, nullable=True)   # disponibilidade hídrica
    n_pixels    = Column(Integer, nullable=True) # pixels válidos

    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("satellite", "lagoa", "ano", "mes", name="uq_water_quality"),
        Index("ix_wq_lagoa_periodo", "lagoa", "ano", "mes"),
    )

    def __repr__(self) -> str:
        return (
            f"<WaterQualityRecord {self.lagoa} {self.ano}-{self.mes:02d} "
            f"ndci={self.ndci_mean}>"
        )


class MapTileRecord(Base):
    """
    Cache de tile URLs XYZ geradas pelo GEE via getMapId().

    Cada registro representa uma camada de índice para um período (ano + mês)
    e lagoa específicos.

    Ciclo de vida:
      1. Worker gera tile → GEE retorna map_id + tile_url
      2. Salvo aqui com expira_at = now + 23 h
      3. Frontend requisita /api/tiles/proxy/{z}/{x}/{y}?k=<tile_key>
         Backend faz proxy autenticado para o GEE
      4. Worker de refresh (a cada 12 h) regenera tiles com expira_at < now + 6 h

    O `tile_key` é composto: "<satellite>|<index_key>|<ano>|<mes>|<lagoa>"
    Usado como chave no proxy — estável mesmo após refresh do map_id.
    """

    __tablename__ = "ndci_map_tiles"

    id          = Column(Integer,      primary_key=True, autoincrement=True)
    satellite   = Column(String(50),   nullable=False)   # ex: "sentinel2"
    index_key   = Column(String(50),   nullable=False)   # ex: "ndci"
    ano         = Column(SmallInteger, nullable=False)
    mes         = Column(SmallInteger, nullable=False)   # sempre mensal para água
    lagoa       = Column(String(100),  nullable=False)

    # GEE tile data
    tile_url    = Column(String(700),  nullable=False)   # URL com {z}/{x}/{y}
    map_id      = Column(String(400),  nullable=False)   # GEE map resource ID
    vis_min     = Column(Float,        nullable=True)
    vis_max     = Column(Float,        nullable=True)
    palette     = Column(JSON,         nullable=True)    # ["hex1", "hex2", ...]
    bounds      = Column(JSON,         nullable=True)    # [west, south, east, north]

    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at   = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "satellite", "index_key", "ano", "mes", "lagoa",
            name="uq_map_tile",
        ),
        Index("ix_map_tiles_index_ano", "index_key", "ano"),
        Index("ix_map_tiles_expires",   "expires_at"),
        Index("ix_map_tiles_lagoa",     "lagoa"),
    )

    @property
    def is_valid(self) -> bool:
        """True se o tile ainda não expirou."""
        return bool(self.expires_at and self.expires_at > datetime.utcnow())

    @property
    def tile_key(self) -> str:
        """Chave estável para uso no proxy endpoint."""
        return f"{self.satellite}|{self.index_key}|{self.ano}|{self.mes}|{self.lagoa}"

    def __repr__(self) -> str:
        return (
            f"<MapTileRecord {self.satellite}/{self.index_key} "
            f"{self.lagoa} {self.ano}-{self.mes:02d} valid={self.is_valid}>"
        )
