"""Tests for state_manager — save/load/delete/corrupted files."""


import pytest

from app.models.schemas import ResumeProfile, UserPreferences, WorkFormat
from app.services.state_manager import StateManager


@pytest.fixture
def sm(tmp_path):
    """Fresh StateManager pointing at a temp dir — no global state pollution."""
    return StateManager(state_dir=tmp_path)


class TestStateBasic:
    def test_save_and_load_preferences(self, sm):
        prefs = UserPreferences(city="Казань", work_format=WorkFormat.remote, salary_min=150000)
        sm.save_preferences(prefs)

        loaded = sm.load_preferences()
        assert loaded is not None
        assert loaded.city == "Казань"
        assert loaded.salary_min == 150000

    def test_save_and_load_profile(self, sm):
        profile = ResumeProfile(
            raw_text="Опытный разработчик",
            name="Иван Иванов",
            position="Senior Python Developer",
            skills=["Python", "FastAPI"],
            experience_years="5 г. 0 мес.",
        )
        sm.save_profile(profile)

        loaded = sm.load_profile()
        assert loaded is not None
        assert loaded.name == "Иван Иванов"
        assert "Python" in loaded.skills


class TestDeleteProfile:
    def test_delete_removes_profile(self, sm):
        profile = ResumeProfile(raw_text="test", name="Иван")
        sm.save_profile(profile)
        assert sm.load_profile() is not None

        sm.delete_profile()
        assert sm.load_profile() is None

    def test_delete_nonexistent_is_noop(self, sm):
        sm.delete_profile()
        assert sm.load_profile() is None

    def test_delete_preserves_preferences(self, sm):
        prefs = UserPreferences(city="Казань", salary_min=150000)
        sm.save_preferences(prefs)

        profile = ResumeProfile(raw_text="test", name="Иван")
        sm.save_profile(profile)

        sm.delete_profile()

        assert sm.load_profile() is None
        loaded_prefs = sm.load_preferences()
        assert loaded_prefs is not None
        assert loaded_prefs.city == "Казань"


class TestSearchParams:
    def test_save_and_load_hash(self, sm):
        sm.save_search_params("abc123")
        assert sm.load_search_params() == "abc123"

    def test_load_when_no_hash(self, sm):
        assert sm.load_search_params() is None

    def test_overwrite_hash(self, sm):
        sm.save_search_params("first")
        sm.save_search_params("second")
        assert sm.load_search_params() == "second"


class TestCorruptedState:
    def test_corrupted_json_returns_none_for_profile(self, sm):
        sm._profile.path.parent.mkdir(parents=True, exist_ok=True)
        sm._profile.path.write_text("{invalid json", encoding="utf-8")

        assert sm.load_profile() is None

    def test_corrupted_json_returns_none_for_preferences(self, sm):
        sm._prefs.path.parent.mkdir(parents=True, exist_ok=True)
        sm._prefs.path.write_text("{invalid json", encoding="utf-8")

        assert sm.load_preferences() is None

    def test_missing_state_files_returns_empty(self, sm):
        assert sm.load_profile() is None
        assert sm.load_preferences() is None
        assert sm.load_search_params() is None


class TestLastReport:
    def test_save_and_load_report(self, sm):
        data = [
            {"vacancy": {"id": "1", "title": "Dev"}, "score": 0.9},
            {"vacancy": {"id": "2", "title": "ML"}, "score": 0.7},
        ]
        sm.save_last_report_vacancies(data)
        loaded = sm.load_last_report()

        assert len(loaded) == 2
        assert loaded[0]["score"] == 0.9

    def test_load_empty_report(self, sm):
        assert sm.load_last_report() == []


class TestSeparateFiles:
    def test_concurrent_saves_dont_corrupt(self, sm):
        prefs = UserPreferences(city="Москва", work_format=WorkFormat.remote)
        sm.save_preferences(prefs)

        profile = ResumeProfile(raw_text="test", name="Тест")
        sm.save_profile(profile)

        loaded_prefs = sm.load_preferences()
        loaded_profile = sm.load_profile()

        assert loaded_prefs is not None
        assert loaded_prefs.city == "Москва"
        assert loaded_profile is not None
        assert loaded_profile.name == "Тест"
