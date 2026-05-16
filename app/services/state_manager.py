"""
Простое хранение состояния пользователя в JSON-файле.
Для MVP это достаточно — в production заменить на БД.
"""

import json
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.models.schemas import ResumeProfile, UserPreferences

STATE_FILE = Path(settings.resumes_path) / "user_state.json"


def _save_state(data: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"State file corrupt: {e}")
    return {}


def save_preferences(prefs: UserPreferences):
    state = _load_state()
    state["preferences"] = prefs.model_dump()
    _save_state(state)
    logger.info("Preferences saved")


def load_preferences() -> UserPreferences | None:
    state = _load_state()
    if "preferences" in state:
        try:
            return UserPreferences(**state["preferences"])
        except Exception as e:
            logger.warning(f"Could not load preferences: {e}")
    return None


def save_profile(profile: ResumeProfile):
    state = _load_state()
    state["profile"] = profile.model_dump()
    _save_state(state)
    logger.info("Resume profile saved")


def load_profile() -> ResumeProfile | None:
    state = _load_state()
    if "profile" in state:
        try:
            return ResumeProfile(**state["profile"])
        except Exception as e:
            logger.warning(f"Could not load profile: {e}")
    return None


def save_last_report_vacancies(vacancies_data: list[dict]):
    state = _load_state()
    state["last_report"] = vacancies_data
    _save_state(state)


def load_last_report() -> list[dict]:
    state = _load_state()
    return state.get("last_report", [])
