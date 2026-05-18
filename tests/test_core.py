"""
Базовые smoke-тесты для проверки корректности импортов и моделей.
Запуск: pytest tests/ -v
"""

from datetime import UTC, datetime


def test_vacancy_model():
    from app.models.schemas import Vacancy

    v = Vacancy(
        id="123",
        title="Python Developer",
        company="TestCo",
        city="Москва",
        url="https://hh.ru/vacancy/123",
        published_at=datetime.now(UTC),
    )
    assert v.id == "123"
    assert v.currency == "RUR"


def test_user_preferences_defaults():
    from app.models.schemas import UserPreferences, WorkFormat

    prefs = UserPreferences()
    assert prefs.city == "Москва"
    assert prefs.work_format == WorkFormat.any_format
    assert prefs.salary_min is None


def test_resume_profile_model():
    from app.models.schemas import ResumeProfile

    p = ResumeProfile(raw_text="Опытный Python-разработчик")
    assert p.raw_text
    assert p.skills == []


def test_scored_vacancy_model():
    from app.models.schemas import ScoredVacancy, Vacancy

    v = Vacancy(
        id="1",
        title="Dev",
        company="Co",
        city="MSK",
        url="https://hh.ru/1",
        published_at=datetime.now(UTC),
    )
    sv = ScoredVacancy(vacancy=v, score=0.85, match_reason="Хорошее совпадение навыков")
    assert sv.score == 0.85


def test_settings_load(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("GIGACHAT_API_KEY", "test_creds")
    monkeypatch.setenv("CHROMA_DB_PATH", "/tmp/test_chroma")
    monkeypatch.setenv("RESUMES_PATH", "/tmp/test_resumes")
    import importlib

    import app.core.config as cfg_mod

    importlib.reload(cfg_mod)
    assert cfg_mod.settings.gigachat_api_key == "test_creds"
