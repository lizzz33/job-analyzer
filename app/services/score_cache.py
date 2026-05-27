"""
Кэш LLM-оценок вакансий.
Хранит vacancy_id → {score, reason, llm_score, content_hash}.
"""

import hashlib
import json
from pathlib import Path

from filelock import FileLock
from loguru import logger

from app.core.config import settings


class ScoreCache:
    def __init__(self, cache_dir: Path | None = None):
        d = cache_dir or Path(settings.resumes_path)
        self._path = d / "score_cache.json"
        self._lock_path = self._path.with_suffix(".lock")

    @staticmethod
    def content_hash(vacancy_text: str, profile_position: str) -> str:
        return hashlib.sha256(f"{vacancy_text}||{profile_position}".encode()).hexdigest()[:16]

    def _read(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, vacancy_id: str, content_hash: str) -> dict | None:
        with FileLock(str(self._lock_path)):
            cache = self._read()
        entry = cache.get(vacancy_id)
        if entry and entry.get("content_hash") == content_hash:
            return entry
        return None

    def put(self, vacancy_id: str, entry: dict) -> None:
        with FileLock(str(self._lock_path)):
            cache = self._read()
            cache[vacancy_id] = entry
            self._write(cache)

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
            logger.info("Score cache cleared")
