"""
Простое хранение состояния пользователя в JSON-файле.
Для MVP это достаточно — в production заменить на БД.
"""

from collections.abc import Callable
import fcntl
import json
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.models.schemas import ResumeProfile, UserPreferences

_DEFAULT_PATH = Path(settings.resumes_path) / "user_state.json"


class StateManager:
    """File-based state storage with locking. Path is injectable for testing."""

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or _DEFAULT_PATH
        self._lock_path = self.state_path.with_suffix(".lock")

    def _acquire_lock(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = open(self._lock_path, "w")  # noqa: SIM115
        fcntl.flock(self._lock_file, fcntl.LOCK_EX)

    def _release_lock(self):
        fcntl.flock(self._lock_file, fcntl.LOCK_UN)
        self._lock_file.close()

    def __enter__(self):
        self._acquire_lock()
        return self

    def __exit__(self, *exc):
        self._release_lock()
        return False

    def _read_raw(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("State file corrupt: {}", e)
        return {}

    def _write_raw(self, data: dict):
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _atomic_update(self, fn: Callable[[dict], None]):
        with self:
            state = self._read_raw()
            fn(state)
            self._write_raw(state)

    def save_preferences(self, prefs: UserPreferences):
        def _update(state: dict):
            state["preferences"] = prefs.model_dump()

        self._atomic_update(_update)
        logger.info("Preferences saved")

    def load_preferences(self) -> UserPreferences | None:
        with self:
            state = self._read_raw()
        if "preferences" in state:
            try:
                return UserPreferences(**state["preferences"])
            except Exception as e:
                logger.warning("Could not load preferences: {}", e)
        return None

    def save_profile(self, profile: ResumeProfile):
        def _update(state: dict):
            state["profile"] = profile.model_dump()

        self._atomic_update(_update)
        logger.info("Resume profile saved")

    def load_profile(self) -> ResumeProfile | None:
        with self:
            state = self._read_raw()
        if "profile" in state:
            try:
                return ResumeProfile(**state["profile"])
            except Exception as e:
                logger.warning("Could not load profile: {}", e)
        return None

    def delete_profile(self):
        def _update(state: dict):
            state.pop("profile", None)

        self._atomic_update(_update)
        logger.info("Resume profile deleted")

    def save_search_params(self, params_hash: str):
        def _update(state: dict):
            state["search_params_hash"] = params_hash

        self._atomic_update(_update)

    def load_search_params(self) -> str | None:
        with self:
            state = self._read_raw()
        return state.get("search_params_hash")

    def save_last_report_vacancies(self, vacancies_data: list[dict]):
        def _update(state: dict):
            state["last_report"] = vacancies_data
            state["last_report_vacancies"] = {
                v["vacancy"]["id"]: v["vacancy"] for v in vacancies_data if "vacancy" in v
            }

        self._atomic_update(_update)

    def load_last_report(self) -> list[dict]:
        with self:
            state = self._read_raw()
        return state.get("last_report", [])


# Default singleton using settings path
state = StateManager()

# Module-level convenience functions backed by the singleton
save_preferences = state.save_preferences
load_preferences = state.load_preferences
save_profile = state.save_profile
load_profile = state.load_profile
delete_profile = state.delete_profile
save_search_params = state.save_search_params
load_search_params = state.load_search_params
save_last_report_vacancies = state.save_last_report_vacancies
load_last_report = state.load_last_report
