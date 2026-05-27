"""
Хранение пользовательских оценок (like/dislike) вакансий.
"""

import json
from pathlib import Path

from filelock import FileLock

from app.core.config import settings
from app.models.schemas import FeedbackType, VacancyFeedback


class FeedbackStore:
    def __init__(self, state_dir: Path | None = None):
        d = state_dir or Path(settings.resumes_path)
        self._path = d / "feedback.json"
        self._lock_path = self._path.with_suffix(".lock")

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

    def add_feedback(self, feedback: VacancyFeedback) -> None:
        with FileLock(str(self._lock_path)):
            data = self._read()
            data[feedback.vacancy_id] = feedback.model_dump(mode="json")
            self._write(data)

    def remove_feedback(self, vacancy_id: str) -> None:
        with FileLock(str(self._lock_path)):
            data = self._read()
            data.pop(vacancy_id, None)
            self._write(data)

    def get_all(self) -> list[VacancyFeedback]:
        return [VacancyFeedback(**v) for v in self._read().values()]

    def get_liked_companies(self) -> set[str]:
        return {
            f.company.lower()
            for f in self.get_all()
            if f.feedback_type == FeedbackType.like and f.company
        }

    def get_disliked_companies(self) -> set[str]:
        return {
            f.company.lower()
            for f in self.get_all()
            if f.feedback_type == FeedbackType.dislike and f.company
        }

    def get_disliked_vacancy_ids(self) -> set[str]:
        return {
            f.vacancy_id
            for f in self.get_all()
            if f.feedback_type == FeedbackType.dislike
        }
