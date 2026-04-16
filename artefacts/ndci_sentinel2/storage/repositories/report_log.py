"""
Repositório para ndci_report_log — controle de idempotência de relatórios.

Um registro por período ISO (ex: "2026-W15").
O UniqueConstraint em storage.models garante que re-tentativas não inserem duplicatas.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from storage.models import ReportLogRecord


class ReportLogRepository:
    """Acesso à tabela ndci_report_log."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Leitura ───────────────────────────────────────────────────────────────

    def already_sent(self, period: str) -> bool:
        """Retorna True se o período já foi enviado com sucesso."""
        rec = (
            self._db.query(ReportLogRecord)
            .filter_by(report_period=period, status="sent")
            .first()
        )
        return rec is not None

    def get_all(self, limit: int = 50) -> list[ReportLogRecord]:
        """Retorna os últimos registros de log, ordenados por data decrescente."""
        return (
            self._db.query(ReportLogRecord)
            .order_by(ReportLogRecord.sent_at.desc())
            .limit(limit)
            .all()
        )

    # ── Escrita ───────────────────────────────────────────────────────────────

    def log(
        self,
        period: str,
        status: str,
        recipients: str,
        error_message: str | None = None,
    ) -> ReportLogRecord:
        """
        Insere ou atualiza o log de um período.

        Se já existir um registro para o período (ex: re-tentativa após erro),
        atualiza o status e a mensagem de erro em vez de duplicar.
        """
        rec = (
            self._db.query(ReportLogRecord)
            .filter_by(report_period=period)
            .first()
        )
        if rec:
            rec.status        = status
            rec.recipients    = recipients
            rec.error_message = error_message
            rec.sent_at       = datetime.utcnow()
        else:
            rec = ReportLogRecord(
                report_period=period,
                recipients=recipients,
                status=status,
                error_message=error_message,
            )
            self._db.add(rec)
        self._db.commit()
        return rec
