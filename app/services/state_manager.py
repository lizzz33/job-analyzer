"""
Хранение состояния пользователя в отдельных JSON-файлах с filelock.
Каждый тип данных — отдельный файл, чтобы не переписывать всё ради одного поля.
"""

import json
from pathlib import Path

from filelock import FileLock
from loguru import logger

from app.core.config import settings
from app.models.schemas import ResumeProfile, UserPreferences

_DATA_DIR = Path(settings.resumes_path)


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("State file corrupt {}: {}", path, e)
    return {}


def _write_json(path: Path, data: dict) -> None:
    _ensure_dir(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class _StateFile:
    """Thread-safe access to a single JSON file using filelock."""

    def __init__(self, path: Path):
        self.path = path
        self._lock_path = path.with_suffix(".lock")

    @property
    def lock(self) -> FileLock:
        return FileLock(str(self._lock_path))

    def read(self) -> dict:
        with self.lock:
            return _read_json(self.path)

    def write(self, data: dict) -> None:
        with self.lock:
            _write_json(self.path, data)

    def update(self, fn) -> None:
        with self.lock:
            data = _read_json(self.path)
            fn(data)
            _write_json(self.path, data)


class StateManager:
    """File-based state storage with separate files per data type."""

    def __init__(self, state_dir: Path | None = None):
        d = state_dir or _DATA_DIR
        self._prefs = _StateFile(d / "preferences.json")
        self._profile = _StateFile(d / "profile.json")
        self._search = _StateFile(d / "search_params.json")
        self._report = _StateFile(d / "last_report.json")

    def save_preferences(self, prefs: UserPreferences) -> None:
        self._prefs.write(prefs.model_dump())
        logger.info("Preferences saved")

    def load_preferences(self) -> UserPreferences | None:
        data = self._prefs.read()
        if data:
            try:
                # Migrate old work_format → work_formats
                if "work_format" in data and "work_formats" not in data:
                    data["work_formats"] = [data.pop("work_format")]
                    self._prefs.write(data)
                    logger.info("Migrated work_format → work_formats in preferences")
                return UserPreferences(**data)
            except Exception as e:
                logger.warning("Could not load preferences: {}", e)
        return None

    def save_profile(self, profile: ResumeProfile) -> None:
        self._profile.write(profile.model_dump())
        logger.info("Resume profile saved")

    def load_profile(self) -> ResumeProfile | None:
        data = self._profile.read()
        if data:
            try:
                return ResumeProfile(**data)
            except Exception as e:
                logger.warning("Could not load profile: {}", e)
        return None

    def delete_profile(self) -> None:
        with self._profile.lock:
            if self._profile.path.exists():
                self._profile.path.unlink()
        logger.info("Resume profile deleted")

    def save_search_params(self, params_hash: str) -> None:
        self._search.write({"hash": params_hash})

    def load_search_params(self) -> str | None:
        return self._search.read().get("hash")

    def save_last_report_vacancies(self, vacancies_data: list[dict]) -> None:
        self._report.write({"vacancies": vacancies_data})

    def load_last_report(self) -> list[dict]:
        return self._report.read().get("vacancies", [])


# Module-level convenience functions backed by lazy singleton
def _get_state() -> StateManager:
    from app.core.deps import get_state_manager
    return get_state_manager()


def save_preferences(*a, **kw): return _get_state().save_preferences(*a, **kw)
def load_preferences(*a, **kw): return _get_state().load_preferences(*a, **kw)
def save_profile(*a, **kw): return _get_state().save_profile(*a, **kw)
def load_profile(*a, **kw): return _get_state().load_profile(*a, **kw)
def delete_profile(*a, **kw): return _get_state().delete_profile(*a, **kw)
def save_search_params(*a, **kw): return _get_state().save_search_params(*a, **kw)
def load_search_params(*a, **kw): return _get_state().load_search_params(*a, **kw)
def save_last_report_vacancies(*a, **kw): return _get_state().save_last_report_vacancies(*a, **kw)
def load_last_report(*a, **kw): return _get_state().load_last_report(*a, **kw)
