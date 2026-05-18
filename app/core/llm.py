"""
Shared utility for creating GigaChat LLM instances with token rotation.
"""

from langchain_gigachat import GigaChat

from app.core.config import settings
from app.core.gigachat_auth import get_verify_ssl_bool, token_provider


class GigaChatLLMFactory:
    """Manages a cached GigaChat LLM instance that refreshes on token change."""

    def __init__(self, **default_kwargs):
        self._llm: GigaChat | None = None
        self._current_token: str | None = None
        self._default_kwargs = default_kwargs

    def get(self, **override_kwargs) -> GigaChat:
        token = token_provider.get_token()
        if self._llm is not None and self._current_token == token:
            return self._llm

        kwargs = {
            "access_token": token,
            "verify_ssl_certs": get_verify_ssl_bool(),
            "model": settings.gigachat_model,
            **self._default_kwargs,
            **override_kwargs,
        }
        self._llm = GigaChat(**kwargs)
        self._current_token = token
        return self._llm
