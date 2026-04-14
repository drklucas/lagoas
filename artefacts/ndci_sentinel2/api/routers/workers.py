"""
Router: /api/workers — disparo manual dos workers de ingestão.

collect-stats e generate-tiles rodam em background: o endpoint responde
imediatamente com status "started" e o trabalho continua em thread pool.
Acompanhe o progresso via `docker compose logs -f api`.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/workers", tags=["Workers"])
logger = logging.getLogger(__name__)


class WorkerResult(BaseModel):
    status: str
    message: str
    detail: dict | None = None


# ── Worker: coleta de estatísticas ────────────────────────────────────────────

def _run_collect_stats_sync(ano_inicio, ano_fim, lagoas, force):
    """Executado em thread pool pelo BackgroundTasks."""
    from ingestion.sentinel2.stats_worker import _sync_collect_stats
    logger.info(
        "collect-stats iniciado — anos=%d..%s lagoas=%s force=%s",
        ano_inicio, ano_fim or "atual", lagoas or "todas", force,
    )
    result = _sync_collect_stats(
        ano_inicio=ano_inicio,
        ano_fim=ano_fim,
        lagoas=lagoas,
        force=force,
    )
    logger.info(
        "collect-stats concluído — salvos=%d pulados=%d erros=%d",
        result.get("saved", 0),
        result.get("skipped", 0),
        len(result.get("errors", [])),
    )
    if result.get("errors"):
        for e in result["errors"]:
            logger.warning("collect-stats erro: %s", e)


@router.post("/collect-stats", response_model=WorkerResult)
async def run_collect_stats(
    background_tasks: BackgroundTasks,
    ano_inicio: int = Query(2017, ge=2017, le=2030),
    ano_fim:    int | None = Query(None),
    lagoa:      str | None = Query(None, description="Lagoa específica ou todas se omitido"),
    force:      bool = Query(False, description="Sobrescreve dados já existentes"),
):
    """
    Coleta estatísticas mensais de NDCI/NDTI/NDWI via GEE reduceRegion.

    **Roda em background** — responde imediatamente com status "started".
    Acompanhe o progresso: `docker compose logs -f api`

    Tempo estimado backfill completo (2017–hoje, 6 lagoas): ~40-90 min.
    """
    lagoas = [lagoa] if lagoa else None
    background_tasks.add_task(
        _run_collect_stats_sync, ano_inicio, ano_fim, lagoas, force
    )
    anos_label = f"{ano_inicio}–{ano_fim or 'atual'}"
    lagoas_label = lagoa or "todas as lagoas"
    return WorkerResult(
        status="started",
        message=f"Coleta iniciada em background: {anos_label}, {lagoas_label}. Acompanhe: docker compose logs -f api",
    )


# ── Worker: geração de tiles visuais ──────────────────────────────────────────

def _run_generate_tiles_sync(ano_inicio, ano_fim, lagoas, indices, force):
    from ingestion.sentinel2.tiles_worker import _sync_generate_tiles
    logger.info(
        "generate-tiles iniciado — anos=%d..%s lagoas=%s indices=%s force=%s",
        ano_inicio, ano_fim or "atual", lagoas or "todas", indices or "todos", force,
    )
    result = _sync_generate_tiles(
        ano_inicio=ano_inicio,
        ano_fim=ano_fim,
        lagoas=lagoas,
        indices=indices,
        force=force,
    )
    logger.info(
        "generate-tiles concluído — salvos=%d pulados=%d erros=%d",
        result.get("saved", 0),
        result.get("skipped", 0),
        len(result.get("errors", [])),
    )
    if result.get("errors"):
        for e in result["errors"]:
            logger.warning("generate-tiles erro: %s", e)


@router.post("/generate-tiles", response_model=WorkerResult)
async def run_generate_tiles(
    background_tasks: BackgroundTasks,
    ano_inicio: int = Query(2017, ge=2017, le=2030),
    ano_fim:    int | None = Query(None),
    lagoa:      str | None = Query(None),
    index_key:  str | None = Query(None, description="ndci | ndti | todos se omitido"),
    force:      bool = Query(False),
):
    """
    Gera tiles visuais XYZ para os índices especificados por lagoa × mês.
    **Roda em background.**
    """
    lagoas  = [lagoa]     if lagoa     else None
    indices = [index_key] if index_key else None
    background_tasks.add_task(
        _run_generate_tiles_sync, ano_inicio, ano_fim, lagoas, indices, force
    )
    return WorkerResult(
        status="started",
        message=f"Geração de tiles iniciada em background: {ano_inicio}–{ano_fim or 'atual'}. Acompanhe: docker compose logs -f api",
    )


# ── Worker: refresh de tiles expirados ────────────────────────────────────────

@router.post("/refresh-tiles", response_model=WorkerResult)
async def run_refresh_tiles(
    window_hours: int = Query(6, ge=1, le=24),
):
    """Regenera tiles prestes a expirar (roda em foreground — geralmente rápido)."""
    from ingestion.sentinel2.refresh_worker import refresh_expiring_tiles

    result = await refresh_expiring_tiles(window_hours=window_hours)
    status  = "error" if result.get("errors") else "ok"
    message = (
        f"Refresh: {result['refreshed']} tiles atualizados."
        if status == "ok"
        else f"Refresh com erros: {len(result['errors'])} falhas."
    )
    return WorkerResult(status=status, message=message, detail=result)


# ── Status do banco ────────────────────────────────────────────────────────────

@router.get("/status")
def worker_status():
    """Conta registros nas tabelas — útil para acompanhar progresso do backfill."""
    from storage.database import SessionLocal
    from storage.models import WaterQualityRecord, MapTileRecord

    db = SessionLocal()
    try:
        wq_total  = db.query(WaterQualityRecord).count()
        wq_lagoas = db.query(WaterQualityRecord.lagoa).distinct().count()
        tile_total = db.query(MapTileRecord).count()
        return {
            "water_quality": {
                "total_records": wq_total,
                "lagoas_com_dados": wq_lagoas,
            },
            "map_tiles": {
                "total_tiles": tile_total,
            },
        }
    finally:
        db.close()
