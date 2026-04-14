"""
Autenticação standalone com o Google Earth Engine.

Ordem de prioridade (mesma do eyefish):
  1. GEE_SERVICE_ACCOUNT_KEY — path para JSON de service account (preferido)
  2. GOOGLE_APPLICATION_CREDENTIALS — fallback (chave BigQuery ou ADC)
  3. Application Default Credentials — `gcloud auth application-default login`

Projeto GEE: GEE_PROJECT ou GOOGLE_CLOUD_PROJECT (default: "acontece-osorio").

Uso:
    from ingestion.gee_auth import init_ee, get_oauth_credentials

    if init_ee():
        import ee
        img = ee.Image(...)

    # Para o proxy de tiles (OAuth Bearer token):
    creds = get_oauth_credentials()
    headers = {"Authorization": f"Bearer {creds.token}"}
"""

from __future__ import annotations

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_ee_initialized = False
_ee_lock = threading.Lock()

_oauth_creds = None
_oauth_lock  = threading.Lock()


def _resolve_key() -> tuple[str, str]:
    """Retorna (project, sa_key_path)."""
    project = os.getenv("GEE_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT", "acontece-osorio")
    sa_key  = os.getenv("GEE_SERVICE_ACCOUNT_KEY") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    return project, sa_key


def init_ee() -> bool:
    """
    Inicializa o SDK earthengine-api.
    Idempotente — chamadas repetidas retornam True sem reinicializar.
    Retorna False em caso de falha (GEE indisponível ou credenciais inválidas).
    """
    global _ee_initialized
    with _ee_lock:
        if _ee_initialized:
            return True
        try:
            import ee
            project, sa_key = _resolve_key()

            if sa_key and os.path.exists(sa_key):
                with open(sa_key) as f:
                    key_data = json.load(f)
                email = key_data["client_email"]
                credentials = ee.ServiceAccountCredentials(email, sa_key)
                ee.Initialize(credentials, project=project)
            else:
                ee.Initialize(project=project)

            logger.info("GEE inicializado — projeto: %s", project)
            _ee_initialized = True
            return True

        except Exception as exc:
            logger.error("GEE init falhou: %s", exc)
            return False


def get_oauth_credentials():
    """
    Retorna credenciais OAuth2 válidas para uso no proxy de tiles.
    Renova automaticamente se expiradas.
    Retorna None se não for possível obter credenciais.
    """
    global _oauth_creds
    with _oauth_lock:
        if _oauth_creds is not None:
            try:
                import google.auth.transport.requests
                if not _oauth_creds.valid:
                    _oauth_creds.refresh(google.auth.transport.requests.Request())
                return _oauth_creds
            except Exception:
                _oauth_creds = None

        _, sa_key = _resolve_key()
        try:
            import google.auth.transport.requests
            if sa_key and os.path.exists(sa_key):
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_file(
                    sa_key,
                    scopes=["https://www.googleapis.com/auth/earthengine"],
                )
            else:
                import google.auth
                creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/earthengine"]
                )
            creds.refresh(google.auth.transport.requests.Request())
            _oauth_creds = creds
            return _oauth_creds
        except Exception as exc:
            logger.error("GEE OAuth: falha ao obter credenciais — %s", exc)
            return None


def extract_tile_url(map_id_info: dict) -> str:
    """
    Extrai a URL de tile XYZ do resultado de ee.Image.getMapId().

    earthengine-api >= 0.1.300: usa tile_fetcher.url_format
    Versões antigas: constrói manualmente a partir de mapid + token.
    """
    fetcher = map_id_info.get("tile_fetcher")
    if fetcher is not None and hasattr(fetcher, "url_format"):
        return fetcher.url_format

    mapid = map_id_info.get("mapid", "")
    token = map_id_info.get("token", "")
    if mapid:
        base = f"https://earthengine.googleapis.com/map/{mapid}/{{z}}/{{x}}/{{y}}"
        return f"{base}?token={token}" if token else base

    raise ValueError(
        f"Não foi possível extrair tile_url. Chaves disponíveis: {list(map_id_info.keys())}"
    )
