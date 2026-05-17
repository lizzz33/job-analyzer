"""
Получение и кэширование GigaChat access token.
Токен обновляется автоматически за 60 секунд до истечения.
"""

import threading
import time
import uuid
import warnings

from loguru import logger
import requests

from app.core.config import settings

warnings.filterwarnings("ignore", message="Unverified HTTPS request")


def _get_ssl_verify() -> str | bool:
    """Return SSL cert path for GigaChat requests.

    Logs a warning if no cert is configured — this disables SSL verification.
    """
    cert_path = settings.gigachat_ca_cert_path
    if cert_path:
        return cert_path
    logger.warning(
        "GIGACHAT_CA_CERT_PATH is not set — SSL verification is DISABLED. "
        "Set this to your Sberbank CA cert path in production."
    )
    return False


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

        response = requests.post(
            self._TOKEN_URL,
            headers=headers,
            data=payload,
            verify=_get_ssl_verify(),
        )
        response.raise_for_status()

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
