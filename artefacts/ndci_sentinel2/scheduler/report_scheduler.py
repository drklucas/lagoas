"""
Scheduler de relatórios semanais e coleta periódica de dados GEE.

Dois jobs APScheduler rodando no mesmo processo:

  Job 1 — collect_recent  (diário, 06h UTC)
    Coleta estatísticas do GEE SOMENTE para o ano corrente.
    Nunca dispara backfill histórico.
    Usa force=False para pular imagens já processadas (idempotente).

  Job 2 — send_weekly_report  (toda segunda-feira, 08h UTC)
    Verifica se já existe log de envio para a semana ISO atual.
    Se não existe, gera o relatório HTML dos últimos LOOKBACK_DAYS dias
    e envia por e-mail para REPORT_RECIPIENTS.
    Registra o resultado em ndci_report_log (idempotência).

Entrypoint:
  python -m scheduler.report_scheduler

Variáveis de ambiente:
  DATABASE_URL           — conexão PostgreSQL (padrão: sqlite)
  GEE_PROJECT            — projeto GEE
  GEE_SERVICE_ACCOUNT_KEY — path para JSON da service account
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM
  REPORT_RECIPIENTS      — e-mails separados por vírgula
  REPORT_LOOKBACK_DAYS   — janela de busca em dias (padrão: 21)
  COLLECT_HOUR_UTC       — hora UTC para coleta diária (padrão: 6)
  REPORT_DAY_OF_WEEK     — dia da semana para relatório (padrão: mon)
  REPORT_HOUR_UTC        — hora UTC para envio do relatório (padrão: 8)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ── Configuração via variáveis de ambiente ─────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


REPORT_RECIPIENTS: list[str] = [
    r.strip() for r in _env("REPORT_RECIPIENTS").split(",") if r.strip()
]
REPORT_LOOKBACK_DAYS: int = int(_env("REPORT_LOOKBACK_DAYS", "21"))

COLLECT_HOUR_UTC:   int = int(_env("COLLECT_HOUR_UTC",  "6"))
REPORT_DAY_OF_WEEK: str = _env("REPORT_DAY_OF_WEEK", "mon")
REPORT_HOUR_UTC:    int = int(_env("REPORT_HOUR_UTC",   "8"))


# ── Job 1: coleta de dados recentes ───────────────────────────────────────────

def job_collect_recent() -> None:
    """
    Coleta estatísticas do GEE apenas para o ano corrente.

    Restringe o intervalo a `ano_inicio=ano_atual` para garantir que
    nunca seja feito backfill histórico acidental.
    force=False pula imagens já processadas — totalmente idempotente.
    """
    ano_atual = datetime.utcnow().year
    logger.info("collect_recent: iniciando coleta para o ano %d", ano_atual)

    try:
        from ingestion.sentinel2.stats_worker import _sync_collect_stats

        result = _sync_collect_stats(
            ano_inicio=ano_atual,
            ano_fim=ano_atual,
            force=False,
        )
        logger.info(
            "collect_recent: concluído — salvos=%d pulados=%d erros=%d",
            result.get("saved", 0),
            result.get("skipped", 0),
            len(result.get("errors", [])),
        )
        for err in result.get("errors", []):
            logger.warning("collect_recent erro: %s", err)

    except Exception as exc:
        logger.error("collect_recent: falha inesperada — %s", exc, exc_info=True)


# ── Job 2: envio do relatório semanal ─────────────────────────────────────────

def job_send_weekly_report(force: bool = False) -> dict:
    """
    Gera e envia o relatório semanal por e-mail.

    Args:
        force: Se True, envia mesmo que o período já tenha sido registrado.

    Returns:
        dict com status, period e detalhes.
    """
    from notifications.email_sender import send_email, smtp_is_configured
    from notifications.report_builder import build_weekly_report
    from storage.database import SessionLocal
    from storage.repositories.report_log import ReportLogRepository

    today = datetime.utcnow().date()
    iso   = today.isocalendar()
    period = f"{iso.year}-W{iso.week:02d}"

    logger.info("send_weekly_report: verificando período %s", period)

    if not REPORT_RECIPIENTS:
        logger.warning(
            "send_weekly_report: REPORT_RECIPIENTS não configurado — relatório ignorado."
        )
        return {"status": "skipped", "reason": "no_recipients", "period": period}

    if not smtp_is_configured():
        logger.warning(
            "send_weekly_report: variáveis SMTP não configuradas — relatório ignorado."
        )
        return {"status": "skipped", "reason": "smtp_not_configured", "period": period}

    db  = SessionLocal()
    log = ReportLogRepository(db)

    try:
        if not force and log.already_sent(period):
            logger.info(
                "send_weekly_report: período %s já enviado — pulando (use force=True para reenviar).",
                period,
            )
            return {"status": "skipped", "reason": "already_sent", "period": period}

        # Gera o relatório com dados dos últimos LOOKBACK_DAYS dias
        logger.info(
            "send_weekly_report: gerando relatório para %s (janela=%d dias)",
            period, REPORT_LOOKBACK_DAYS,
        )
        payload = build_weekly_report(
            db=db,
            lookback_days=REPORT_LOOKBACK_DAYS,
            report_period=period,
        )

        # Envia o e-mail
        send_email(
            subject=payload.subject,
            html_body=payload.html,
            recipients=REPORT_RECIPIENTS,
        )

        # Registra o envio bem-sucedido
        log.log(
            period=period,
            status="sent",
            recipients=",".join(REPORT_RECIPIENTS),
        )
        logger.info(
            "send_weekly_report: enviado com sucesso — período=%s destinatários=%d "
            "critico=%s elevado=%s",
            period, len(REPORT_RECIPIENTS),
            payload.has_critical, payload.has_elevated,
        )
        return {
            "status":       "sent",
            "period":       period,
            "recipients":   len(REPORT_RECIPIENTS),
            "has_critical": payload.has_critical,
            "has_elevated": payload.has_elevated,
        }

    except Exception as exc:
        error_msg = str(exc)
        logger.error(
            "send_weekly_report: erro ao enviar relatório %s — %s",
            period, error_msg, exc_info=True,
        )
        try:
            log.log(
                period=period,
                status="error",
                recipients=",".join(REPORT_RECIPIENTS),
                error_message=error_msg,
            )
        except Exception as log_exc:
            logger.error("send_weekly_report: falha ao registrar erro no log: %s", log_exc)
        return {"status": "error", "period": period, "error": error_msg}

    finally:
        db.close()


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Inicia o scheduler bloqueante com os dois jobs configurados.

    Aguarda o banco ficar disponível antes de iniciar (retry com backoff).
    """
    logger.info("Scheduler iniciando...")
    logger.info(
        "Configuração: collect_recent=06h UTC | report=%s %dh UTC | "
        "lookback=%d dias | recipients=%d",
        REPORT_DAY_OF_WEEK, REPORT_HOUR_UTC,
        REPORT_LOOKBACK_DAYS, len(REPORT_RECIPIENTS),
    )

    if not REPORT_RECIPIENTS:
        logger.warning(
            "REPORT_RECIPIENTS não configurado. "
            "O job de relatório rodará mas não enviará e-mails."
        )

    # Aguarda o banco ficar disponível (importante no start do Docker Compose)
    _wait_for_db()

    scheduler = BlockingScheduler(timezone="UTC")

    # Job 1: coleta diária às 06h UTC
    scheduler.add_job(
        job_collect_recent,
        trigger=CronTrigger(hour=COLLECT_HOUR_UTC, minute=0, timezone="UTC"),
        id="collect_recent",
        name="Coleta dados GEE — ano corrente",
        max_instances=1,          # evita sobreposição se a coleta demorar
        misfire_grace_time=3600,  # tolera até 1h de atraso (reinício do container)
        replace_existing=True,
    )

    # Job 2: relatório semanal (toda segunda, 08h UTC por padrão)
    scheduler.add_job(
        job_send_weekly_report,
        trigger=CronTrigger(
            day_of_week=REPORT_DAY_OF_WEEK,
            hour=REPORT_HOUR_UTC,
            minute=0,
            timezone="UTC",
        ),
        id="send_weekly_report",
        name="Relatório semanal por e-mail",
        max_instances=1,
        misfire_grace_time=7200,  # tolera até 2h de atraso
        replace_existing=True,
    )

    logger.info(
        "Jobs agendados: %s",
        [j.name for j in scheduler.get_jobs()],
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler encerrado.")


def _wait_for_db(max_retries: int = 30, delay_s: int = 5) -> None:
    """Aguarda o banco PostgreSQL ficar disponível antes de iniciar os jobs."""
    from storage.database import engine
    from sqlalchemy import text

    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Banco de dados disponível.")
            return
        except Exception as exc:
            logger.warning(
                "Banco indisponível (tentativa %d/%d): %s — aguardando %ds...",
                attempt, max_retries, exc, delay_s,
            )
            time.sleep(delay_s)

    logger.error(
        "Banco de dados não disponível após %d tentativas. "
        "Verifique DATABASE_URL e a saúde do serviço db.",
        max_retries,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
