"""
Shared fixtures for all tests.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.models.schemas import ResumeProfile, UserPreferences, Vacancy, WorkFormat


@pytest.fixture
def sample_vacancy() -> Vacancy:
    return Vacancy(
        id="12345",
        title="Python Developer",
        company="TestCorp",
        city="Москва",
        salary_from=200000,
        salary_to=300000,
        url="https://hh.ru/vacancy/12345",
        published_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_profile() -> ResumeProfile:
    return ResumeProfile(
        raw_text="Опытный Python-разработчик с 5 годами опыта.",
        name="Иван Иванов",
        position="Senior Python Developer",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
        experience_years="5 г. 0 мес.",
        city="Москва",
        summary="Backend-разработчик, специализация — высоконагруженные сервисы.",
    )


@pytest.fixture
def sample_prefs() -> UserPreferences:
    return UserPreferences(
        city="Москва",
        work_format=WorkFormat.remote,
        salary_min=200000,
        keywords=["python", "backend"],
    )


@pytest.fixture
def mock_token_provider():
    """Patch GigaChatTokenProvider so no real HTTP calls happen."""
    with patch("app.core.gigachat_auth.token_provider") as mock:
        mock.get_token.return_value = "fake-test-token"
        yield mock
