"""
FastAPI app — NDCI/Sentinel-2 standalone service.

Variáveis de ambiente:
  DATABASE_URL            — PostgreSQL ou SQLite (default: sqlite:///./ndci_sentinel2.db)
  GEE_SERVICE_ACCOUNT_KEY — Path para JSON de service account GEE
  GEE_PROJECT             — Projeto GEE (default: acontece-osorio)

Execução:
  uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api.routers import (
    water_quality_router,
    tiles_router,
    predictions_router,
    workers_router,
    notifications_router,
)

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="NDCI Sentinel-2 API",
    description=(
        "Monitoramento de qualidade da água em lagoas costeiras via "
        "Normalized Difference Chlorophyll Index (Sentinel-2, GEE)."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(water_quality_router)
app.include_router(tiles_router)
app.include_router(predictions_router)
app.include_router(workers_router)
app.include_router(notifications_router)

# Arquivos estáticos do frontend (CSS, JS)
app.mount("/static", StaticFiles(directory=os.path.join(_FRONTEND_DIR)), name="static")


@app.on_event("startup")
async def on_startup():
    """Garante que as tabelas existem no banco ao iniciar."""
    from storage.database import create_all_tables
    create_all_tables()
    logging.getLogger(__name__).info("Tabelas verificadas/criadas.")


@app.get("/")
def root():
    """Serve o frontend HTML."""
    index = os.path.join(_FRONTEND_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"service": "NDCI Sentinel-2", "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}
