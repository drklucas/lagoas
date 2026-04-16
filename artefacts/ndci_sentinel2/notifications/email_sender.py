"""
Enviador de e-mail via SMTP com TLS.

Usa somente a biblioteca padrão (smtplib + email.mime) — sem dependências extras.

Configuração via variáveis de ambiente:
  SMTP_HOST      — servidor SMTP (ex: smtp.gmail.com, smtp.sendgrid.net)
  SMTP_PORT      — porta (default: 587 para STARTTLS)
  SMTP_USER      — usuário / endereço de login
  SMTP_PASSWORD  — senha ou API key (ex: App Password do Gmail, apikey do SendGrid)
  SMTP_FROM      — endereço remetente (default: igual a SMTP_USER)
  SMTP_USE_SSL   — "true" para porta 465 (SSL direto); default "false" (STARTTLS)

Credenciais nunca hardcoded — lidas exclusivamente do ambiente injetado
pelo Docker Compose via env_file ou Docker secrets.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def send_email(
    subject: str,
    html_body: str,
    recipients: list[str],
    plain_body: str | None = None,
) -> None:
    """
    Envia um e-mail com corpo HTML (e texto simples de fallback).

    Args:
        subject:    Assunto do e-mail.
        html_body:  Corpo em HTML (CSS inline para compatibilidade com clientes de e-mail).
        recipients: Lista de endereços de destino.
        plain_body: Corpo em texto simples (fallback). Se None, gerado automaticamente.

    Raises:
        ValueError: Se alguma variável de ambiente obrigatória estiver ausente.
        smtplib.SMTPException: Em caso de falha de autenticação ou envio.
    """
    smtp_host = _cfg("SMTP_HOST")
    smtp_user = _cfg("SMTP_USER")
    smtp_pass = _cfg("SMTP_PASSWORD")

    if not smtp_host or not smtp_user or not smtp_pass:
        raise ValueError(
            "Variáveis de ambiente SMTP_HOST, SMTP_USER e SMTP_PASSWORD "
            "devem estar configuradas para envio de e-mail."
        )

    smtp_port = int(_cfg("SMTP_PORT", "587"))
    smtp_from = _cfg("SMTP_FROM") or smtp_user
    use_ssl   = _cfg("SMTP_USE_SSL", "false").lower() == "true"

    if not recipients:
        logger.warning("send_email: lista de destinatários vazia — e-mail não enviado.")
        return

    # Monta a mensagem
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_from
    msg["To"]      = ", ".join(recipients)

    # Parte texto simples (fallback para clientes que não renderizam HTML)
    if plain_body is None:
        plain_body = _html_to_plain(subject)
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))

    # Parte HTML (preferida pelos clientes modernos)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    logger.info(
        "Enviando e-mail '%s' para %d destinatário(s) via %s:%d",
        subject, len(recipients), smtp_host, smtp_port,
    )

    try:
        if use_ssl:
            # Porta 465 — SSL direto
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, recipients, msg.as_string())
        else:
            # Porta 587 — STARTTLS (recomendado)
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, recipients, msg.as_string())

        logger.info("E-mail enviado com sucesso para: %s", ", ".join(recipients))

    except smtplib.SMTPAuthenticationError as exc:
        logger.error("Falha de autenticação SMTP (%s:%d): %s", smtp_host, smtp_port, exc)
        raise
    except smtplib.SMTPException as exc:
        logger.error("Erro SMTP ao enviar e-mail: %s", exc)
        raise


def _html_to_plain(subject: str) -> str:
    """Gera um corpo de texto simples mínimo como fallback."""
    return (
        f"{subject}\n\n"
        "Este e-mail contém um relatório de qualidade da água das lagoas costeiras "
        "do Litoral Norte do RS.\n\n"
        "Para visualizar o relatório completo, abra este e-mail em um cliente que "
        "suporte HTML ou acesse o dashboard:\n"
        "https://drklucas.github.io/lagoas/\n\n"
        "---\n"
        "NDCI/Sentinel-2 · Monitoramento via Google Earth Engine\n"
        "Metodologia: Pi & Guasselli, SBSR 2025\n"
    )


def smtp_is_configured() -> bool:
    """Retorna True se as variáveis SMTP obrigatórias estão presentes."""
    return bool(_cfg("SMTP_HOST") and _cfg("SMTP_USER") and _cfg("SMTP_PASSWORD"))
