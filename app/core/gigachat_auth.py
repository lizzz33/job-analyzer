"""
Получение и кэширование GigaChat access token.
Токен обновляется автоматически за 60 секунд до истечения.
"""

import os
import threading
import time
import uuid
import warnings

from loguru import logger
import requests

from app.core.config import settings

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# Set to "1" in production to require SSL cert.
_SSL_REQUIRED = os.getenv("GIGACHAT_SSL_REQUIRED", "").lower() in ("1", "true", "yes")


def _setup_ssl() -> None:
    """Configure SSL: set SSL_CERT_FILE so all HTTP libs pick up the CA cert."""
    cert_path = settings.gigachat_ca_cert_path
    if cert_path and os.path.isfile(cert_path):
        os.environ["SSL_CERT_FILE"] = cert_path
        os.environ["REQUESTS_CA_BUNDLE"] = cert_path
        logger.info("SSL CA cert configured: {}", cert_path)
    elif _SSL_REQUIRED:
        raise RuntimeError(
            "GIGACHAT_CA_CERT_PATH is not set or file not found, but SSL is required. "
            "Set GIGACHAT_CA_CERT_PATH or unset GIGACHAT_SSL_REQUIRED for dev."
        )
    else:
        logger.warning(
            "GIGACHAT_CA_CERT_PATH is not set — SSL verification is DISABLED. "
            "Set this to your Sberbank CA cert path in production."
        )


def _get_ssl_verify() -> str | bool:
    """Return value for requests verify= parameter (supports cert path)."""
    cert_path = settings.gigachat_ca_cert_path
    if cert_path and os.path.isfile(cert_path):
        return cert_path
    return False


def get_verify_ssl_bool() -> bool:
    """Return bool for GigaChat SDK verify_ssl_certs parameter."""
    cert_path = settings.gigachat_ca_cert_path
    if cert_path and os.path.isfile(cert_path):
        return True
    if _SSL_REQUIRED:
        raise RuntimeError(
            "GIGACHAT_CA_CERT_PATH is not set or file not found, but SSL is required."
        )
    return False


# Configure SSL on module import.
_setup_ssl()


class GigaChatTokenProvider:
    _TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

    def __init__(self):
        self._token: str | None = None
        self._expires_at: float = 0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            return self._refresh()

    def _refresh(self) -> str:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {settings.gigachat_api_key}",
        }
        payload = f"scope={settings.gigachat_scope}&grant_type=client_credentials"

        response = None
        try:
            response = requests.post(
                self._TOKEN_URL,
                headers=headers,
                data=payload,
                verify=_get_ssl_verify(),
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error("GigaChat token request failed (status={}): {}", getattr(response, "status_code", "N/A"), e)
            raise

        data = response.json()
        expires_in = data.get("expires_in", 1800)
        self._token = data["access_token"]
        self._expires_at = time.time() + expires_in - 60

        logger.debug("GigaChat token refreshed, expires in {}s", expires_in)
        return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0


token_provider = GigaChatTokenProvider()
