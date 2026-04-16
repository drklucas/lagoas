"""
Router: /api/notifications — disparo manual de relatórios e histórico de envios.

Endpoints:
  POST /api/notifications/trigger-report   — gera e envia relatório imediatamente
  GET  /api/notifications/report-log       — histórico dos envios (últimos 50)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from storage.database import get_db

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])
logger = logging.getLogger(__name__)


# ── Schemas de resposta ────────────────────────────────────────────────────────

class TriggerReportResponse(BaseModel):
    status:  str
    message: str
    detail:  dict | None = None


class ReportLogEntry(BaseModel):
    id:            int
    report_period: str
    recipients:    str
    status:        str
    error_message: str | None
    sent_at:       str   # ISO string

    class Config:
        from_attributes = True


# ── POST /api/notifications/trigger-report ────────────────────────────────────

def _run_report_sync(force: bool, lookback_days: int, times: int) -> None:
    """Executado em thread pool pelo BackgroundTasks."""
    from scheduler.report_scheduler import job_send_weekly_report
    logger.info(
        "trigger-report: iniciando (force=%s lookback_days=%d times=%d)",
        force, lookback_days, times,
    )
    for attempt in range(1, times + 1):
        result = job_send_weekly_report(force=force)
        logger.info(
            "trigger-report: envio %d/%d concluído — %s",
            attempt, times, result,
        )


@router.post("/trigger-report", response_model=TriggerReportResponse)
async def trigger_report(
    background_tasks: BackgroundTasks,
    force: bool = Query(
        True,
        description=(
            "Se True, envia mesmo que o período já tenha sido enviado. "
            "Útil para reenvio manual ou testes."
        ),
    ),
    times: int = Query(
        1,
        ge=1,
        le=100,
        description=(
            "Quantidade de envios consecutivos no mesmo disparo. "
            "Use para teste massivo (ex: times=20)."
        ),
    ),
    lookback_days: int = Query(
        21,
        ge=1,
        le=90,
        description="Janela de busca de observações recentes em dias.",
    ),
):
    """
    Dispara o relatório semanal imediatamente em background.

    O relatório é gerado com dados dos últimos `lookback_days` dias e enviado
    para os destinatários configurados em REPORT_RECIPIENTS.

    **Roda em background** — responde imediatamente com status "started".
    """
    background_tasks.add_task(_run_report_sync, force, lookback_days, times)
    return TriggerReportResponse(
        status="started",
        message=(
            f"Geração do relatório iniciada em background "
            f"(force={force}, lookback_days={lookback_days}, times={times}). "
            f"Acompanhe: docker compose logs -f scheduler"
        ),
    )


# ── GET /api/notifications/report-log ─────────────────────────────────────────

@router.get("/report-log")
def get_report_log(
    limit: int = Query(50, ge=1, le=200, description="Número máximo de registros"),
    db: Session = Depends(get_db),
):
    """
    Retorna o histórico dos relatórios enviados.

    Útil para verificar idempotência, diagnosticar falhas de envio
    e confirmar que os relatórios estão sendo gerados corretamente.
    """
    from storage.repositories.report_log import ReportLogRepository

    repo    = ReportLogRepository(db)
    records = repo.get_all(limit=limit)

    return {
        "total": len(records),
        "records": [
            {
                "id":            r.id,
                "report_period": r.report_period,
                "recipients":    r.recipients,
                "status":        r.status,
                "error_message": r.error_message,
                "sent_at":       r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in records
        ],
    }
