"""
Базовые smoke-тесты для проверки корректности импортов и моделей.
Запуск: pytest tests/ -v
"""

from datetime import datetime

# ── Models ────────────────────────────────────────────────────────────────────


def test_vacancy_model():
    from app.models.schemas import Vacancy

    v = Vacancy(
        id="123",
        title="Python Developer",
        company="TestCo",
        city="Москва",
        url="https://hh.ru/vacancy/123",
        published_at=datetime.utcnow(),
    )
    assert v.id == "123"
    assert v.currency == "RUR"


def test_user_preferences_defaults():
    from app.models.schemas import UserPreferences, WorkFormat

    prefs = UserPreferences()
    assert prefs.city == "Москва"
    assert prefs.work_format == WorkFormat.any
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
        published_at=datetime.utcnow(),
    )
    sv = ScoredVacancy(vacancy=v, score=0.85, match_reason="Хорошее совпадение навыков")
    assert sv.score == 0.85


# ── Config ────────────────────────────────────────────────────────────────────


def test_settings_load(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("GIGACHAT_API_KEY", "test_creds")
    monkeypatch.setenv("CHROMA_DB_PATH", "/tmp/test_chroma")
    monkeypatch.setenv("RESUMES_PATH", "/tmp/test_resumes")
    # Re-import with patched env
    import importlib

    import app.core.config as cfg_mod

    importlib.reload(cfg_mod)
    assert cfg_mod.settings.gigachat_api_key == "test_creds"


# ── HH Fetcher ────────────────────────────────────────────────────────────────


def test_hh_parse_vacancy():
    from app.services.hh_fetcher import _parse_vacancy

    item = {
        "id": "99999",
        "name": "Senior Python Developer",
        "employer": {"name": "ООО Тест"},
        "area": {"name": "Москва"},
        "salary": {"from": 200000, "to": 350000, "currency": "RUR"},
        "schedule": {"id": "remote"},
        "alternate_url": "https://hh.ru/vacancy/99999",
        "published_at": "2025-01-15T10:00:00+0300",
        "snippet": {"requirement": "Python 3 лет", "responsibility": "Разработка API"},
    }
    v = _parse_vacancy(item)
    assert v is not None
    assert v.id == "99999"
    assert v.salary_from == 200000
    assert v.company == "ООО Тест"


def test_hh_parse_vacancy_missing_salary():
    from app.services.hh_fetcher import _parse_vacancy

    item = {
        "id": "11111",
        "name": "Аналитик",
        "employer": {"name": "Corp"},
        "area": {"name": "СПб"},
        "salary": None,
        "schedule": {"id": "fullDay"},
        "alternate_url": "https://hh.ru/vacancy/11111",
        "published_at": "2025-01-10T09:00:00+0300",
        "snippet": {},
    }
    v = _parse_vacancy(item)
    assert v is not None
    assert v.salary_from is None
    assert v.salary_to is None


# ── Vector Store ──────────────────────────────────────────────────────────────


def test_vacancy_to_doc():
    from app.models.schemas import Vacancy
    from app.services.vector_store import _vacancy_to_doc

    v = Vacancy(
        id="42",
        title="ML Engineer",
        company="AI Corp",
        city="Москва",
        salary_from=300000,
        salary_to=500000,
        description="Разработка ML-моделей",
        url="https://hh.ru/42",
        published_at=datetime.utcnow(),
    )
    doc = _vacancy_to_doc(v)
    assert "ML Engineer" in doc.page_content
    assert "AI Corp" in doc.page_content
    assert "300" in doc.page_content
    assert doc.metadata["id"] == "42"


# ── State Manager ─────────────────────────────────────────────────────────────


def test_state_save_load(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMES_PATH", str(tmp_path))
    monkeypatch.setenv("GIGACHAT_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("GIGACHAT_API_KEY", "test")
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))

    import importlib

    import app.core.config as cfg_mod
    import app.services.state_manager as sm_mod

    importlib.reload(cfg_mod)
    importlib.reload(sm_mod)

    from app.models.schemas import UserPreferences, WorkFormat

    prefs = UserPreferences(city="Казань", work_format=WorkFormat.remote, salary_min=150000)
    sm_mod.save_preferences(prefs)

    loaded = sm_mod.load_preferences()
    assert loaded is not None
    assert loaded.city == "Казань"
    assert loaded.salary_min == 150000


def test_profile_save_load(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUMES_PATH", str(tmp_path))
    monkeypatch.setenv("GIGACHAT_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("GIGACHAT_API_KEY", "test")
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))

    import importlib

    import app.core.config as cfg_mod
    import app.services.state_manager as sm_mod

    importlib.reload(cfg_mod)
    importlib.reload(sm_mod)

    from app.models.schemas import ResumeProfile

    profile = ResumeProfile(
        raw_text="Опытный разработчик",
        name="Иван Иванов",
        position="Senior Python Developer",
        skills=["Python", "FastAPI", "PostgreSQL"],
        experience_years=5.0,
    )
    sm_mod.save_profile(profile)

    loaded = sm_mod.load_profile()
    assert loaded is not None
    assert loaded.name == "Иван Иванов"
    assert "Python" in loaded.skills


# ── Pipeline helpers ──────────────────────────────────────────────────────────


def test_build_search_queries():
    from app.core.pipeline import _build_search_queries
    from app.models.schemas import ResumeProfile, UserPreferences

    profile = ResumeProfile(
        raw_text="...",
        position="Data Engineer",
        skills=["Python", "Spark", "Airflow", "SQL", "Kafka"],
    )
    prefs = UserPreferences(keywords=["data engineer", "etl developer"])
    queries = _build_search_queries(profile, prefs)

    assert "Data Engineer" in queries
    assert "data engineer" in queries
    assert len(queries) <= 5
    # No duplicates
    assert len(queries) == len(set(queries))
