"""Tests for ScoreCache."""

import pytest

from app.services.score_cache import ScoreCache


@pytest.fixture
def cache(tmp_path):
    return ScoreCache(cache_dir=tmp_path)


class TestScoreCache:
    def test_miss_returns_none(self, cache):
        assert cache.get("v1", "hash1") is None

    def test_put_and_get(self, cache):
        entry = {"llm_score": 0.8, "reason": "good", "content_hash": "abc"}
        cache.put("v1", entry)
        result = cache.get("v1", "abc")
        assert result == entry

    def test_hash_mismatch_returns_none(self, cache):
        cache.put("v1", {"llm_score": 0.8, "reason": "", "content_hash": "abc"})
        assert cache.get("v1", "different_hash") is None

    def test_overwrite(self, cache):
        cache.put("v1", {"llm_score": 0.5, "reason": "ok", "content_hash": "h"})
        cache.put("v1", {"llm_score": 0.9, "reason": "great", "content_hash": "h"})
        result = cache.get("v1", "h")
        assert result["llm_score"] == 0.9

    def test_clear(self, cache):
        cache.put("v1", {"llm_score": 0.5, "reason": "", "content_hash": "h"})
        cache.clear()
        assert cache.get("v1", "h") is None

    def test_content_hash_deterministic(self):
        h1 = ScoreCache.content_hash("text", "position")
        h2 = ScoreCache.content_hash("text", "position")
        assert h1 == h2

    def test_content_hash_differs_on_input_change(self):
        h1 = ScoreCache.content_hash("text1", "position")
        h2 = ScoreCache.content_hash("text2", "position")
        assert h1 != h2
