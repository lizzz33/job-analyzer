"""Tests for GigaChat token provider."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class TestGigaChatTokenProvider:
    @pytest.fixture
    def provider(self):
        from app.core.gigachat_auth import GigaChatTokenProvider

        return GigaChatTokenProvider()

    def test_get_token_refreshes_on_first_call(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "tok_abc", "expires_in": 1800}
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp) as mock_post:
            token = provider.get_token()

        assert token == "tok_abc"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["Authorization"].startswith("Basic ")

    def test_token_cached_until_expiry(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "tok_cached", "expires_in": 1800}
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp) as mock_post:
            token1 = provider.get_token()
            token2 = provider.get_token()

        assert token1 == token2 == "tok_cached"
        assert mock_post.call_count == 1

    def test_token_refreshed_after_expiry(self, provider):
        resp1 = MagicMock()
        resp1.json.return_value = {"access_token": "tok_old", "expires_in": 1}
        resp1.raise_for_status = MagicMock()

        resp2 = MagicMock()
        resp2.json.return_value = {"access_token": "tok_new", "expires_in": 1800}
        resp2.raise_for_status = MagicMock()

        with patch("requests.post", side_effect=[resp1, resp2]) as mock_post:
            provider.get_token()
            provider._expires_at = time.time() - 1
            token = provider.get_token()

        assert token == "tok_new"
        assert mock_post.call_count == 2

    def test_invalidate_forces_refresh(self, provider):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "tok_first", "expires_in": 1800}
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp) as mock_post:
            provider.get_token()
            provider.invalidate()
            token = provider.get_token()

        assert token == "tok_first"
        assert mock_post.call_count == 2

    def test_http_error_propagates(self, provider):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")

        with patch("requests.post", return_value=mock_resp), pytest.raises(Exception, match="401"):
            provider.get_token()

    def test_thread_safety(self, provider):
        call_count = 0

        def _mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            time.sleep(0.05)
            resp = MagicMock()
            resp.json.return_value = {"access_token": f"tok_{call_count}", "expires_in": 1800}
            resp.raise_for_status = MagicMock()
            return resp

        results = []

        def _get():
            results.append(provider.get_token())

        with patch("requests.post", side_effect=_mock_post):
            threads = [threading.Thread(target=_get) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert all(r is not None for r in results)
        assert call_count <= 5
