"""Tests for FastAPI endpoints in app.main."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def _get_client(tmp_path, monkeypatch):
    """Build TestClient with paths overridden via monkeypatch on live module."""
    monkeypatch.setenv("RESUMES_PATH", str(tmp_path))
    monkeypatch.setenv("CHROMA_DB_PATH", str(tmp_path / "chroma"))

    import app.core.config as cfg_mod

    cfg_mod.settings.resumes_path = str(tmp_path)
    cfg_mod.settings.chroma_db_path = str(tmp_path / "chroma")

    import app.main as main_mod

    return TestClient(main_mod.app), main_mod


class TestHealthAndRoot:
    def test_health(self, tmp_path, monkeypatch):
        client, _ = _get_client(tmp_path, monkeypatch)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_root_redirects_to_docs(self, tmp_path, monkeypatch):
        client, _ = _get_client(tmp_path, monkeypatch)
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/docs" in resp.headers["location"]


class TestResumeEndpoints:
    def test_upload_unsupported_format(self, tmp_path, monkeypatch):
        client, _ = _get_client(tmp_path, monkeypatch)
        fake_file = io.BytesIO(b"data")
        resp = client.post(
            "/resume/upload",
            files={"file": ("resume.xlsx", fake_file, "application/octet-stream")},
        )
        assert resp.status_code == 400

    def test_get_profile_not_found(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)
        mock_state = MagicMock()
        mock_state.load_profile.return_value = None
        with patch.object(mod, "get_state_manager", return_value=mock_state):
            resp = client.get("/resume/profile")
        assert resp.status_code == 404

    def test_delete_profile(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)
        mock_state = MagicMock()
        with patch.object(mod, "get_state_manager", return_value=mock_state):
            resp = client.delete("/resume/profile")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_upload_and_get_profile(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        from app.models.schemas import ResumeProfile

        mock_profile = ResumeProfile(raw_text="test", name="Иван")
        mock_parser = MagicMock()
        mock_parser.parse = AsyncMock(return_value=mock_profile)
        mock_state = MagicMock()

        with (
            patch.object(mod, "get_resume_parser", return_value=mock_parser),
            patch.object(mod, "get_state_manager", return_value=mock_state),
        ):
            fake_file = io.BytesIO(b"resume content text")
            resp = client.post(
                "/resume/upload",
                files={"file": ("resume.txt", fake_file, "text/plain")},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_upload_parse_error(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        mock_parser = MagicMock()
        mock_parser.parse = AsyncMock(side_effect=Exception("Parse failed"))
        mock_state = MagicMock()

        with (
            patch.object(mod, "get_resume_parser", return_value=mock_parser),
            patch.object(mod, "get_state_manager", return_value=mock_state),
        ):
            fake_file = io.BytesIO(b"bad content")
            resp = client.post(
                "/resume/upload",
                files={"file": ("resume.txt", fake_file, "text/plain")},
            )

        assert resp.status_code == 500


class TestPreferencesEndpoints:
    def test_set_and_get_preferences(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        prefs_data = {
            "city": "Казань",
            "work_formats": ["remote"],
            "salary_min": 150000,
            "include_no_salary": False,
            "excluded_companies": [],
            "preferred_companies": [],
            "extra_interests": "",
            "keywords": ["python"],
            "max_results_per_run": 50,
        }

        from app.models.schemas import UserPreferences

        mock_state = MagicMock()
        mock_state.load_preferences.return_value = UserPreferences(city="Казань", salary_min=150000)

        with patch.object(mod, "get_state_manager", return_value=mock_state):
            resp_post = client.post("/preferences", json=prefs_data)
            assert resp_post.status_code == 200

            resp_get = client.get("/preferences")
            assert resp_get.status_code == 200
            data = resp_get.json()
            assert data["city"] == "Казань"
            assert data["salary_min"] == 150000

    def test_get_default_preferences(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        mock_state = MagicMock()
        mock_state.load_preferences.return_value = None

        with patch.object(mod, "get_state_manager", return_value=mock_state):
            resp = client.get("/preferences")

        assert resp.status_code == 200
        data = resp.json()
        assert data["city"] == "Москва"


class TestAnalysisEndpoints:
    def test_run_analysis_no_profile(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        mock_state = MagicMock()
        mock_state.load_profile.return_value = None
        with patch.object(mod, "get_state_manager", return_value=mock_state):
            resp = client.post("/analysis/run")

        assert resp.status_code == 400

    def test_analysis_status(self, tmp_path, monkeypatch):
        client, _ = _get_client(tmp_path, monkeypatch)
        resp = client.get("/analysis/status")
        assert resp.status_code == 200
        assert resp.json()["running"] is False

    def test_get_report_empty(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        mock_state = MagicMock()
        mock_state.load_last_report.return_value = []
        with patch.object(mod, "get_state_manager", return_value=mock_state):
            resp = client.get("/analysis/report")

        assert resp.status_code == 200
        data = resp.json()
        assert data["vacancies"] == []


class TestStatsEndpoint:
    def test_stats(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        mock_vs = MagicMock()
        mock_vs.get_total_count.return_value = 5
        mock_state = MagicMock()
        mock_state.load_profile.return_value = None
        mock_state.load_preferences.return_value = None

        with (
            patch.object(mod, "get_vector_store", return_value=mock_vs),
            patch.object(mod, "get_state_manager", return_value=mock_state),
        ):
            resp = client.get("/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["vacancies_in_db"] == 5
        assert data["has_resume"] is False


class TestClearDataEndpoint:
    def test_clear(self, tmp_path, monkeypatch):
        client, mod = _get_client(tmp_path, monkeypatch)

        mock_vs = MagicMock()
        with patch.object(mod, "get_vector_store", return_value=mock_vs):
            resp = client.delete("/data/clear")

        assert resp.status_code == 200
        mock_vs.clear.assert_called_once()
