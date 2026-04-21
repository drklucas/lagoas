"""
Construtor do relatório semanal de qualidade da água.

Consulta SOMENTE registros recentes de ndci_image_records
(janela configurável via lookback_days — padrão 21 dias).
Nunca lê o histórico completo.

Fluxo:
  1. Para cada lagoa ativa, busca a observação mais recente
     dentro da janela [now - lookback_days, now].
  2. Classifica o status NDCI (bom / moderado / elevado / crítico).
  3. Gera imagem de satélite (OSM + overlay NDCI via GEE) por lagoa.
  4. Renderiza o template Jinja2 weekly_report.html.j2.
  5. Gera PDF via WeasyPrint (se disponível).
  6. Retorna ReportPayload com HTML, PDF, assunto e flags de alerta.
"""

from __future__ import annotations

import base64
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import ACTIVE_LAGOAS, LAGOAS
from core.index_registry import classify
from storage.models import ImageRecord

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_ASSETS_DIR    = Path(__file__).parent / "assets"

# Fuso horário de Brasília (UTC-3, sem ajuste de horário de verão)
_BRT = timezone(timedelta(hours=-3))

_STATUS_COLORS: dict[str, str] = {
    "bom":       "#22c55e",
    "moderado":  "#eab308",
    "elevado":   "#f97316",
    "critico":   "#ef4444",
    "sem_dados": "#94a3b8",
}


def _load_asset_b64(filename: str, mime: str = "image/png") -> str:
    """Carrega asset como data URI base64. Retorna string vazia se não encontrado."""
    p = _ASSETS_DIR / filename
    if not p.exists():
        logger.warning("Asset não encontrado: %s", p)
        return ""
    with open(p, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


_LOGO_IFRS_B64:    str = _load_asset_b64("logo_ifrs.png")
_LOGO_PROJECT_B64: str = _load_asset_b64("logo_project.png")

# ── Constantes de tamanho de imagem ───────────────────────────────────────────
_MAP_IMG_W = 480
_MAP_IMG_H = 320
_TILE_PX   = 256


@dataclass
class LagoaReport:
    """Dados de uma lagoa para o relatório."""
    lagoa:                  str
    data:                   str | None
    ndci_mean:              float | None
    ndci_p90:               float | None
    ndti_mean:              float | None
    n_pixels:               int | None
    cloud_pct:              float | None
    status:                 str
    status_color:           str
    sem_observacao_recente: bool = False
    map_image_bytes:        bytes | None = None  # PNG bruto da imagem de satélite


@dataclass
class ReportPayload:
    """Resultado gerado pelo build_weekly_report."""
    html:          str
    subject:       str
    report_period: str
    has_critical:  bool
    has_elevated:  bool
    lagoas_data:   list[LagoaReport] = field(default_factory=list)
    pdf_bytes:     bytes | None = None

    @property
    def image_attachments(self) -> list[tuple[bytes, str]]:
        """Retorna lista de (bytes_png, nome_arquivo) para anexar ao e-mail."""
        result = []
        for lg in self.lagoas_data:
            if lg.map_image_bytes:
                safe = lg.lagoa.replace(" ", "_").replace("/", "_")
                result.append(
                    (lg.map_image_bytes, f"NDCI_{safe}_{lg.data}.png")
                )
        return result


# ── Funções de geração de mapa ─────────────────────────────────────────────────

def _lon_to_tx(lon: float, z: int) -> int:
    n = 2 ** z
    return int((lon + 180.0) / 360.0 * n)


def _lat_to_ty(lat: float, z: int) -> int:
    n   = 2 ** z
    rad = math.radians(lat)
    return int((1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * n)


def _best_zoom(bbox: list[float], target_tiles: float = 3.0) -> int:
    """Retorna zoom para que o bbox maior ocupe ~target_tiles tiles."""
    west, south, east, north = bbox
    max_span = max(east - west, north - south)
    if max_span <= 0:
        return 12
    z = math.log2(target_tiles * 360.0 / max_span)
    return max(8, min(16, int(z)))


def _generate_lagoa_map_image(
    db: Session,
    lagoa_name: str,
    record_date: date,
) -> bytes | None:
    """
    Gera PNG de mapa centrado na lagoa, com basemap OSM + overlay NDCI do GEE.

    Retorna None se Pillow/httpx não estiverem disponíveis ou em caso de falha.
    """
    try:
        from PIL import Image, ImageDraw  # type: ignore
    except ImportError:
        logger.warning("Pillow não disponível — sem imagem de satélite")
        return None

    try:
        import httpx  # já está em requirements.txt
    except ImportError:
        logger.warning("httpx não disponível — sem imagem de satélite")
        return None

    try:
        cfg = LAGOAS.get(lagoa_name)
        if not cfg:
            return None

        bbox = cfg["bbox"]           # [west, south, east, north]
        west, south, east, north = bbox

        z = _best_zoom(bbox)
        n = 2 ** z

        # Padding de 15 % ao redor do bbox
        pad_lon = (east - west)   * 0.15
        pad_lat = (north - south) * 0.15

        x_min = _lon_to_tx(west - pad_lon,  z)
        x_max = _lon_to_tx(east + pad_lon,  z)
        y_min = _lat_to_ty(north + pad_lat, z)   # norte → y menor
        y_max = _lat_to_ty(south - pad_lat, z)   # sul   → y maior

        # Garante ordenação correta e limita ao range válido
        x_min, x_max = sorted([max(0, x_min), min(n - 1, x_max)])
        y_min, y_max = sorted([max(0, y_min), min(n - 1, y_max)])

        # Limita tamanho do canvas (máx 5×5 tiles = 1280×1280 px)
        while (x_max - x_min + 1) * (y_max - y_min + 1) > 25 and z > 8:
            z -= 1
            n = 2 ** z
            x_min = max(0, _lon_to_tx(west - pad_lon, z))
            x_max = min(n - 1, _lon_to_tx(east + pad_lon, z))
            y_min = max(0, _lat_to_ty(north + pad_lat, z))
            y_max = min(n - 1, _lat_to_ty(south - pad_lat, z))
            x_min, x_max = sorted([x_min, x_max])
            y_min, y_max = sorted([y_min, y_max])

        num_x = x_max - x_min + 1
        num_y = y_max - y_min + 1
        canvas = Image.new("RGB", (num_x * _TILE_PX, num_y * _TILE_PX), (220, 220, 220))

        osm_ua = (
            "lagoas-rs-ndci-monitor/1.0 "
            "(IFRS Osorio; research use; lucasnevesp3@gmail.com)"
        )

        # ── Basemap OSM ────────────────────────────────────────────────────────
        with httpx.Client(timeout=8.0, headers={"User-Agent": osm_ua}) as client:
            for tx in range(x_min, x_max + 1):
                for ty in range(y_min, y_max + 1):
                    try:
                        r = client.get(
                            f"https://tile.openstreetmap.org/{z}/{tx}/{ty}.png"
                        )
                        if r.status_code == 200:
                            tile = Image.open(BytesIO(r.content)).convert("RGB")
                            px = (tx - x_min) * _TILE_PX
                            py = (ty - y_min) * _TILE_PX
                            canvas.paste(tile, (px, py))
                    except Exception:
                        pass

        # ── Overlay NDCI via GEE ──────────────────────────────────────────────
        try:
            from storage.repositories.map_tiles import MapTileRepository
            from ingestion.gee_auth import get_oauth_credentials

            repo    = MapTileRepository(db)
            tile_rec = repo.get(
                satellite="sentinel2",
                index_key="ndci",
                data=record_date,
                lagoa=lagoa_name,
            )

            if tile_rec and tile_rec.map_id:
                creds = get_oauth_credentials()
                if creds and creds.token:
                    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                    gee_hdr = {
                        "Authorization": f"Bearer {creds.token}",
                        "User-Agent":    osm_ua,
                    }
                    with httpx.Client(timeout=12.0, headers=gee_hdr) as gcli:
                        for tx in range(x_min, x_max + 1):
                            for ty in range(y_min, y_max + 1):
                                try:
                                    url = (
                                        f"https://earthengine.googleapis.com"
                                        f"/v1/{tile_rec.map_id}/tiles/{z}/{tx}/{ty}"
                                    )
                                    r = gcli.get(url)
                                    if r.status_code == 200:
                                        gtile = Image.open(BytesIO(r.content)).convert("RGBA")
                                        # 85 % de opacidade sobre o basemap
                                        r2, g2, b2, a2 = gtile.split()
                                        a2 = a2.point(lambda v: int(v * 0.85))
                                        gtile = Image.merge("RGBA", (r2, g2, b2, a2))
                                        px = (tx - x_min) * _TILE_PX
                                        py = (ty - y_min) * _TILE_PX
                                        overlay.paste(gtile, (px, py), mask=a2)
                                except Exception:
                                    pass

                    canvas_rgba = canvas.convert("RGBA")
                    canvas_rgba = Image.alpha_composite(canvas_rgba, overlay)
                    canvas = canvas_rgba.convert("RGB")
        except Exception as exc:
            logger.warning("GEE overlay falhou (%s): %s", lagoa_name, exc)

        # ── Pós-processamento ─────────────────────────────────────────────────
        canvas = canvas.resize((_MAP_IMG_W, _MAP_IMG_H), Image.LANCZOS)

        draw = ImageDraw.Draw(canvas)
        # Atribuição OSM
        osm_text = "© OpenStreetMap contributors"
        text_w   = len(osm_text) * 6 + 6
        draw.rectangle(
            [0, _MAP_IMG_H - 16, text_w, _MAP_IMG_H],
            fill=(255, 255, 255),
        )
        draw.text((3, _MAP_IMG_H - 14), osm_text, fill=(80, 80, 80))
        # Borda
        draw.rectangle([0, 0, _MAP_IMG_W - 1, _MAP_IMG_H - 1], outline="#1a4a7a", width=2)

        out = BytesIO()
        canvas.save(out, format="PNG", optimize=True)
        return out.getvalue()

    except Exception as exc:
        logger.warning("Falha ao gerar imagem para %s: %s", lagoa_name, exc)
        return None


# ── Consulta ao banco ──────────────────────────────────────────────────────────

def _get_recent_records(
    db: Session,
    lagoas: list[str],
    since: date,
    satellite: str = "sentinel2",
) -> dict[str, ImageRecord]:
    """
    Retorna o registro mais recente de cada lagoa desde `since`.

    Usa subquery MAX(data) por lagoa para evitar N+1 queries.
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


# ── Builder principal ──────────────────────────────────────────────────────────

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
        report_period: período ISO (ex: "2026-W15"). Se None, calcula automaticamente.
        satellite:     satélite de origem (padrão "sentinel2").

    Returns:
        ReportPayload com html, pdf_bytes, subject e metadados.
    """
    now   = datetime.now(_BRT)
    today = now.date()
    since = today - timedelta(days=lookback_days)

    if report_period is None:
        iso = today.isocalendar()
        report_period = f"{iso.year}-W{iso.week:02d}"

    active: list[str] = ACTIVE_LAGOAS or list(LAGOAS.keys())

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

    # Gera imagens de satélite para as lagoas com observação recente
    for lg in lagoas_data:
        if not lg.sem_observacao_recente and lg.data:
            try:
                lg.map_image_bytes = _generate_lagoa_map_image(
                    db, lg.lagoa, date.fromisoformat(lg.data)
                )
            except Exception as exc:
                logger.warning("Imagem %s: %s", lg.lagoa, exc)

    # Assunto do e-mail
    if has_critical:
        alert_label = "🚨 ALERTA CRÍTICO"
    elif has_elevated:
        alert_label = "⚠ ALERTA ELEVADO"
    else:
        alert_label = "✓ Normal"

    subject = f"[Lagoas RS] Boletim Semanal {report_period} — {alert_label}"

    # Renderiza template Jinja2
    jinja_env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = jinja_env.get_template("weekly_report.html.j2")

    context: dict[str, Any] = {
        "subject":          subject,
        "report_period":    report_period,
        "generated_at":     now.strftime("%d/%m/%Y %H:%M (Brasília)"),
        "lookback_days":    lookback_days,
        "lagoas":           [_lagoa_to_dict(lg) for lg in lagoas_data],
        "logo_ifrs_b64":    _LOGO_IFRS_B64,
        "logo_project_b64": _LOGO_PROJECT_B64,
    }

    html = template.render(**context)

    # Gera PDF via WeasyPrint
    pdf_bytes: bytes | None = None
    try:
        import weasyprint  # type: ignore
        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
        logger.info("PDF gerado: %d bytes", len(pdf_bytes))
    except ImportError:
        logger.warning("WeasyPrint não instalado — PDF não gerado")
    except Exception as exc:
        logger.warning("Falha ao gerar PDF: %s", exc)

    return ReportPayload(
        html=html,
        subject=subject,
        report_period=report_period,
        has_critical=has_critical,
        has_elevated=has_elevated,
        lagoas_data=lagoas_data,
        pdf_bytes=pdf_bytes,
    )


def _lagoa_to_dict(lg: LagoaReport) -> dict[str, Any]:
    """Converte LagoaReport em dict para o template Jinja2."""
    map_b64: str | None = None
    if lg.map_image_bytes:
        map_b64 = (
            "data:image/png;base64,"
            + base64.b64encode(lg.map_image_bytes).decode()
        )
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
        "map_image_b64":          map_b64,
    }
