"""
Construtor do relatório semanal de qualidade da água.

Consulta SOMENTE registros recentes de ndci_image_records
(janela configurável via lookback_days — padrão 21 dias).
Nunca lê o histórico completo.

Fluxo:
  1. Para cada lagoa ativa, busca a observação mais recente
     dentro da janela [now - lookback_days, now].
  2. Classifica o status NDCI (bom / moderado / elevado / crítico).
  3. Renderiza o template Jinja2 weekly_report.html.j2.
  4. Retorna ReportPayload com HTML, assunto e flags de alerta.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import ACTIVE_LAGOAS, LAGOAS
from core.index_registry import classify
from storage.models import ImageRecord

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_STATUS_COLORS: dict[str, str] = {
    "bom":           "#22c55e",
    "moderado":      "#eab308",
    "elevado":       "#f97316",
    "critico":       "#ef4444",
    "sem_dados":     "#94a3b8",
}


@dataclass
class LagoaReport:
    """Dados de uma lagoa para o relatório."""
    lagoa:                str
    data:                 str | None         # "YYYY-MM-DD" da observação mais recente
    ndci_mean:            float | None
    ndci_p90:             float | None
    ndti_mean:            float | None
    n_pixels:             int | None
    cloud_pct:            float | None
    status:               str                # bom | moderado | elevado | critico | sem_dados
    status_color:         str
    sem_observacao_recente: bool = False


@dataclass
class ReportPayload:
    """Resultado gerado pelo build_weekly_report."""
    html:         str
    subject:      str
    report_period: str
    has_critical: bool
    has_elevated: bool
    lagoas_data:  list[LagoaReport] = field(default_factory=list)
    pdf_bytes:    bytes | None = None   # reservado para extensão futura com WeasyPrint


def _get_recent_records(
    db: Session,
    lagoas: list[str],
    since: date,
    satellite: str = "sentinel2",
) -> dict[str, ImageRecord]:
    """
    Retorna o registro mais recente de cada lagoa desde `since`.

    Usa uma subquery para pegar o MAX(data) por lagoa e depois
    faz o join para trazer o registro completo — evita N+1 queries.
    """
    subq = (
        db.query(
            ImageRecord.lagoa,
            func.max(ImageRecord.data).label("max_data"),
        )
        .filter(
            ImageRecord.satellite == satellite,
            ImageRecord.lagoa.in_(lagoas),
            ImageRecord.data >= since,
        )
        .group_by(ImageRecord.lagoa)
        .subquery()
    )

    records = (
        db.query(ImageRecord)
        .join(
            subq,
            (ImageRecord.lagoa == subq.c.lagoa)
            & (ImageRecord.data == subq.c.max_data),
        )
        .filter(ImageRecord.satellite == satellite)
        .all()
    )

    return {r.lagoa: r for r in records}


def build_weekly_report(
    db: Session,
    lookback_days: int = 21,
    report_period: str | None = None,
    satellite: str = "sentinel2",
) -> ReportPayload:
    """
    Monta o relatório semanal com dados dos últimos `lookback_days` dias.

    Args:
        db:            sessão SQLAlchemy aberta pelo chamador.
        lookback_days: janela de busca em dias (padrão 21).
        report_period: período ISO para o assunto (ex: "2026-W15").
                       Se None, calcula a partir da data atual.
        satellite:     satélite de origem (padrão "sentinel2").

    Returns:
        ReportPayload com html, subject e metadados.
    """
    now   = datetime.utcnow()
    today = now.date()
    since = today - timedelta(days=lookback_days)

    if report_period is None:
        iso = today.isocalendar()
        report_period = f"{iso.year}-W{iso.week:02d}"

    # Lagoas a incluir no relatório
    active: list[str] = ACTIVE_LAGOAS or list(LAGOAS.keys())

    # Busca os registros mais recentes em uma única query
    recent: dict[str, ImageRecord] = _get_recent_records(
        db, active, since, satellite=satellite
    )

    lagoas_data: list[LagoaReport] = []
    has_critical = False
    has_elevated = False

    for lagoa_name in sorted(active):
        rec = recent.get(lagoa_name)

        if rec is None:
            lagoas_data.append(LagoaReport(
                lagoa=lagoa_name,
                data=None,
                ndci_mean=None,
                ndci_p90=None,
                ndti_mean=None,
                n_pixels=None,
                cloud_pct=None,
                status="sem_dados",
                status_color=_STATUS_COLORS["sem_dados"],
                sem_observacao_recente=True,
            ))
            continue

        status = classify("ndci", rec.ndci_mean)
        if status == "critico":
            has_critical = True
        elif status == "elevado":
            has_elevated = True

        lagoas_data.append(LagoaReport(
            lagoa=lagoa_name,
            data=rec.data.isoformat() if rec.data else None,
            ndci_mean=rec.ndci_mean,
            ndci_p90=rec.ndci_p90,
            ndti_mean=rec.ndti_mean,
            n_pixels=rec.n_pixels,
            cloud_pct=rec.cloud_pct,
            status=status,
            status_color=_STATUS_COLORS.get(status, "#94a3b8"),
            sem_observacao_recente=False,
        ))

    # Monta o assunto do e-mail
    if has_critical:
        alert_label = "🚨 ALERTA CRÍTICO"
    elif has_elevated:
        alert_label = "⚠ ALERTA ELEVADO"
    else:
        alert_label = "✓ Normal"

    subject = (
        f"[Lagoas RS] Boletim Semanal {report_period} — {alert_label}"
    )

    # Renderiza o template Jinja2
    jinja_env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = jinja_env.get_template("weekly_report.html.j2")

    # Converte dataclasses em dicts para o Jinja2
    context: dict[str, Any] = {
        "subject":       subject,
        "report_period": report_period,
        "generated_at":  now.strftime("%d/%m/%Y %H:%M UTC"),
        "lookback_days": lookback_days,
        "lagoas":        [_lagoa_to_dict(lg) for lg in lagoas_data],
    }

    html = template.render(**context)

    return ReportPayload(
        html=html,
        subject=subject,
        report_period=report_period,
        has_critical=has_critical,
        has_elevated=has_elevated,
        lagoas_data=lagoas_data,
    )


def _lagoa_to_dict(lg: LagoaReport) -> dict[str, Any]:
    """Converte LagoaReport em dict para consumo pelo template Jinja2."""
    return {
        "lagoa":                  lg.lagoa,
        "data":                   lg.data,
        "ndci_mean":              lg.ndci_mean,
        "ndci_p90":               lg.ndci_p90,
        "ndti_mean":              lg.ndti_mean,
        "n_pixels":               lg.n_pixels,
        "cloud_pct":              lg.cloud_pct,
        "status":                 lg.status,
        "status_color":           lg.status_color,
        "sem_observacao_recente": lg.sem_observacao_recente,
    }
