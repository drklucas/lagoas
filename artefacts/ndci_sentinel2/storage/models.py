"""
Modelos SQLAlchemy standalone para o sistema NDCI/Sentinel-2.

Quatro modelos:
  - ImageRecord         → estatísticas por imagem individual (fonte primária)
  - WaterQualityRecord  → agregados mensais derivados dos ImageRecords (ML + API legado)
  - MapTileRecord       → URLs de tiles XYZ para visualização no mapa
  - ReportLogRecord     → log de idempotência para relatórios enviados por e-mail

A granularidade por imagem (ImageRecord) foi adicionada para reproduzir a
metodologia de Pi & Guasselli (SBSR 2025), que captura imagens individuais
com até 10 dias de intervalo em vez de composições mensais.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
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


class ImageRecord(Base):
    """
    Estatísticas por imagem individual de satélite para cada lagoa.

    Fonte primária de dados — uma linha por cena Sentinel-2 que passou pelos
    filtros de qualidade (cobertura de nuvens < 20%, pixels válidos mínimos).
    Os agregados mensais em WaterQualityRecord são derivados desta tabela.

    Metodologia: Pi & Guasselli (SBSR 2025) — capturas individuais com até
    10 dias de intervalo preservam picos de bloom de curta duração.
    """

    __tablename__ = "ndci_image_records"

    id          = Column(Integer,      primary_key=True, autoincrement=True)
    satellite   = Column(String(50),   nullable=False, index=True)
    lagoa       = Column(String(100),  nullable=False, index=True)
    data        = Column(Date,         nullable=False)          # data da imagem
    ano         = Column(SmallInteger, nullable=False)          # derivado de data
    mes         = Column(SmallInteger, nullable=False)          # derivado de data

    # Índices espectrais calculados na geometria erodida (com buffer negativo)
    ndci_mean   = Column(Float, nullable=True)
    ndci_p90    = Column(Float, nullable=True)
    ndci_p10    = Column(Float, nullable=True)
    ndti_mean   = Column(Float, nullable=True)
    ndwi_mean   = Column(Float, nullable=True)
    fai_mean    = Column(Float, nullable=True)

    n_pixels    = Column(Integer, nullable=True)   # pixels válidos após máscaras
    cloud_pct   = Column(Float,   nullable=True)   # CLOUDY_PIXEL_PERCENTAGE da cena

    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("satellite", "lagoa", "data", name="uq_image_record"),
        Index("ix_ir_lagoa_data",    "lagoa", "data"),
        Index("ix_ir_lagoa_periodo", "lagoa", "ano", "mes"),
    )

    def __repr__(self) -> str:
        return (
            f"<ImageRecord {self.lagoa} {self.data} "
            f"ndci={self.ndci_mean}>"
        )


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

    Cada registro representa uma camada de índice para uma imagem individual
    (data exata do satélite) de uma lagoa específica.

    Ciclo de vida:
      1. Worker gera tile → GEE retorna map_id + tile_url
      2. Salvo aqui com expires_at = now + 23 h
      3. Frontend requisita /api/tiles/proxy/{z}/{x}/{y}?k=<tile_key>
         Backend faz proxy autenticado para o GEE
      4. Worker de refresh regenera tiles com expires_at < now + 6 h

    O `tile_key` é composto: "<satellite>|<index_key>|<YYYY-MM-DD>|<lagoa>"
    Usado como chave no proxy — estável mesmo após refresh do map_id.

    Metodologia: Pi & Guasselli (SBSR 2025) — granularidade por imagem individual.
    """

    __tablename__ = "ndci_map_tiles"

    id          = Column(Integer,      primary_key=True, autoincrement=True)
    satellite   = Column(String(50),   nullable=False)   # ex: "sentinel2"
    index_key   = Column(String(50),   nullable=False)   # ex: "ndci"
    data        = Column(Date,         nullable=True)    # data exata da imagem (YYYY-MM-DD)
    ano         = Column(SmallInteger, nullable=True)    # derivado de data (para agrupamento)
    mes         = Column(SmallInteger, nullable=True)    # derivado de data (para agrupamento)
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
            "satellite", "index_key", "data", "lagoa",
            name="uq_map_tile",
        ),
        Index("ix_map_tiles_index_data", "index_key", "data"),
        Index("ix_map_tiles_expires",    "expires_at"),
        Index("ix_map_tiles_lagoa",      "lagoa"),
    )

    @property
    def is_valid(self) -> bool:
        """True se o tile ainda não expirou."""
        return bool(self.expires_at and self.expires_at > datetime.utcnow())

    @property
    def tile_key(self) -> str:
        """Chave estável para uso no proxy endpoint."""
        data_str = self.data.isoformat() if self.data else "nodate"
        return f"{self.satellite}|{self.index_key}|{data_str}|{self.lagoa}"

    def __repr__(self) -> str:
        return (
            f"<MapTileRecord {self.satellite}/{self.index_key} "
            f"{self.lagoa} {self.data} valid={self.is_valid}>"
        )


class ReportLogRecord(Base):
    """
    Log de idempotência para relatórios semanais enviados por e-mail.

    Um registro por período ISO (ex: "2026-W15").
    O UniqueConstraint garante que re-tentativas não inserem duplicatas.
    Permite reenvio controlado via update do status.
    """

    __tablename__ = "ndci_report_log"

    id             = Column(Integer,    primary_key=True, autoincrement=True)
    report_period  = Column(String(20), nullable=False)   # ex: "2026-W15"
    recipients     = Column(String,     nullable=False)   # separados por vírgula
    status         = Column(String(20), nullable=False)   # sent | skipped | error
    error_message  = Column(String,     nullable=True)
    sent_at        = Column(DateTime,   nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("report_period", name="uq_report_period"),
        Index("ix_report_log_sent_at", "sent_at"),
    )

    def __repr__(self) -> str:
        return f"<ReportLogRecord {self.report_period} status={self.status}>"
