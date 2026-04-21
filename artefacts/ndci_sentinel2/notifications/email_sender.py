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
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
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
    pdf_attachment: bytes | None = None,
    pdf_filename: str = "relatorio_ndci.pdf",
    image_attachments: list[tuple[bytes, str]] | None = None,
) -> None:
    """
    Envia e-mail com corpo HTML, PDF opcional e imagens opcionais em anexo.

    Args:
        subject:           Assunto do e-mail.
        html_body:         Corpo HTML (pode conter data URIs para imagens inline).
        recipients:        Lista de destinatários.
        plain_body:        Fallback texto simples. Se None, gerado automaticamente.
        pdf_attachment:    Bytes do PDF a anexar (opcional).
        pdf_filename:      Nome do arquivo PDF no e-mail.
        image_attachments: Lista de (bytes_png, nome_arquivo) a anexar (opcional).

    Raises:
        ValueError:             Variáveis SMTP obrigatórias ausentes.
        smtplib.SMTPException:  Falha de autenticação ou envio.
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

    if plain_body is None:
        plain_body = _html_to_plain(subject)

    has_attachments = bool(pdf_attachment) or bool(image_attachments)

    if has_attachments:
        # Estrutura: mixed → [alternative → plain + html] + pdf + images
        msg = MIMEMultipart("mixed")
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(plain_body, "plain", "utf-8"))
        body_part.attach(MIMEText(html_body,  "html",  "utf-8"))
        msg.attach(body_part)

        if pdf_attachment:
            pdf_part = MIMEApplication(pdf_attachment, _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition", "attachment", filename=pdf_filename
            )
            msg.attach(pdf_part)

        for img_bytes, img_name in (image_attachments or []):
            img_part = MIMEImage(img_bytes, _subtype="png")
            img_part.add_header(
                "Content-Disposition", "attachment", filename=img_name
            )
            msg.attach(img_part)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    msg["Subject"] = subject
    msg["From"]    = smtp_from
    msg["To"]      = ", ".join(recipients)

    logger.info(
        "Enviando e-mail '%s' para %d destinatário(s) via %s:%d "
        "(pdf=%s imagens=%d)",
        subject,
        len(recipients),
        smtp_host,
        smtp_port,
        pdf_attachment is not None,
        len(image_attachments or []),
    )

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, recipients, msg.as_string())
        else:
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
    """Gera corpo de texto simples mínimo como fallback para clientes sem HTML."""
    return (
        f"{subject}\n\n"
        "Este e-mail contém o boletim semanal de qualidade da água das lagoas costeiras "
        "do Litoral Norte do RS, gerado via NDCI/Sentinel-2.\n\n"
        "Para visualizar o relatório completo com imagens de satélite, abra este e-mail "
        "em um cliente que suporte HTML ou acesse o dashboard:\n"
        "https://drklucas.github.io/lagoas/\n\n"
        "O relatório completo em PDF está anexado a este e-mail.\n\n"
        "---\n"
        "NDCI/Sentinel-2 · Monitoramento via Google Earth Engine\n"
        "Metodologia: Pi & Guasselli, SBSR 2025\n"
        "IFRS Osório\n"
    )


def smtp_is_configured() -> bool:
    """Retorna True se as variáveis SMTP obrigatórias estão presentes."""
    return bool(_cfg("SMTP_HOST") and _cfg("SMTP_USER") and _cfg("SMTP_PASSWORD"))
