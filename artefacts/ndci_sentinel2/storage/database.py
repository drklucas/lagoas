"""
Fábrica de engine/session SQLAlchemy — standalone, sem dependência do eyefish.

Lê DATABASE_URL do ambiente. Exemplo de valores:
  postgresql+psycopg2://user:pass@localhost:5432/ndci_db
  sqlite:///./ndci_local.db        ← útil para testes locais

Variável opcional NDCI_DB_POOL_SIZE (default: 5).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite:///./ndci_sentinel2.db",   # fallback para desenvolvimento local
)
_POOL_SIZE: int = int(os.getenv("NDCI_DB_POOL_SIZE", "5"))

# SQLite não suporta pool_size/max_overflow
_engine_kwargs: dict = {}
if not _DATABASE_URL.startswith("sqlite"):
    _engine_kwargs = {"pool_size": _POOL_SIZE, "max_overflow": 10}

engine = create_engine(_DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base declarativa para todos os modelos deste sistema."""


def get_db():
    """Dependência FastAPI — yield de sessão com fechamento garantido."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables() -> None:
    """Cria todas as tabelas (útil para testes e setup inicial)."""
    from storage import models  # noqa: F401 — garante registro dos modelos
    Base.metadata.create_all(bind=engine)
