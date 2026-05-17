"""
Базовые smoke-тесты для проверки корректности импортов и моделей.
Запуск: pytest tests/ -v
"""

from datetime import UTC, datetime

# ── Models ────────────────────────────────────────────────────────────────────


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
        published_at=datetime.now(UTC),
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


def _make_vacancy_card_html(
    title="Senior Python Developer",
    vacancy_id="99999",
    company="ООО Тест",
    city="Москва",
    salary_text="от 200 000 ₽",
):
    from bs4 import BeautifulSoup

    html = f"""
    <div data-qa="vacancy-serp__vacancy">
      <a data-qa="serp-item__title" href="https://hh.ru/vacancy/{vacancy_id}">{title}</a>
      <span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>
      <span data-qa="vacancy-serp__vacancy-address">{city}</span>
      <span>{salary_text}</span>
    </div>
    """
    soup = BeautifulSoup(html, "lxml")
    return soup.select_one('[data-qa="vacancy-serp__vacancy"]')


def test_hh_parse_vacancy_card():
    from app.services.hh_fetcher import _parse_vacancy_card

    card = _make_vacancy_card_html()
    v = _parse_vacancy_card(card)
    assert v is not None
    assert v.id == "99999"
    assert v.salary_from == 200000
    assert v.company == "ООО Тест"


def test_hh_parse_vacancy_card_missing_salary():
    from app.services.hh_fetcher import _parse_vacancy_card

    card = _make_vacancy_card_html(
        title="Аналитик",
        vacancy_id="11111",
        company="Corp",
        city="СПб",
        salary_text="",
    )
    v = _parse_vacancy_card(card)
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
        published_at=datetime.now(UTC),
    )
    doc = _vacancy_to_doc(v)
    assert "ML Engineer" in doc.page_content
    assert "AI Corp" in doc.page_content
    assert "300" in doc.page_content
    assert doc.metadata["id"] == "42"


# ── State Manager ─────────────────────────────────────────────────────────────


def test_state_save_load(tmp_path):
    from app.models.schemas import UserPreferences, WorkFormat
    from app.services.state_manager import StateManager

    sm = StateManager(state_path=tmp_path / "user_state.json")
    prefs = UserPreferences(city="Казань", work_format=WorkFormat.remote, salary_min=150000)
    sm.save_preferences(prefs)

    loaded = sm.load_preferences()
    assert loaded is not None
    assert loaded.city == "Казань"
    assert loaded.salary_min == 150000


def test_profile_save_load(tmp_path):
    from app.models.schemas import ResumeProfile
    from app.services.state_manager import StateManager

    sm = StateManager(state_path=tmp_path / "user_state.json")
    profile = ResumeProfile(
        raw_text="Опытный разработчик",
        name="Иван Иванов",
        position="Senior Python Developer",
        skills=["Python", "FastAPI", "PostgreSQL"],
        experience_years="5 г. 0 мес.",
    )
    sm.save_profile(profile)

    loaded = sm.load_profile()
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
    # "data engineer" is deduplicated with "Data Engineer" (case-insensitive)
    assert len(queries) <= 5
    # No duplicates (case-insensitive)
    assert len(queries) == len({q.lower() for q in queries})
