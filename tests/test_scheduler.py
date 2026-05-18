"""Tests for scheduler — daily job behaviour."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import DailyReport, ResumeProfile, ScoredVacancy, UserPreferences, Vacancy


class TestDailyJob:
    @pytest.mark.asyncio
    async def test_skips_when_no_profile(self):
        mock_state = MagicMock()
        mock_state.load_profile.return_value = None
        with (
            patch("scheduler.daily_job.get_state_manager", return_value=mock_state),
        ):
            from scheduler.daily_job import daily_job

            await daily_job()

    @pytest.mark.asyncio
    async def test_runs_pipeline_when_profile_exists(self):
        profile = ResumeProfile(raw_text="dev", position="Dev", skills=["Python"])
        report = DailyReport(total_found=5, top_vacancies=[], summary_text="ok")

        mock_state = MagicMock()
        mock_state.load_profile.return_value = profile
        mock_state.load_preferences.return_value = None

        with (
            patch("scheduler.daily_job.get_state_manager", return_value=mock_state),
            patch("scheduler.daily_job.run_analysis_pipeline", new_callable=AsyncMock, return_value=report) as mock_pipeline,
        ):
            from scheduler.daily_job import daily_job

            await daily_job()

        mock_pipeline.assert_awaited_once_with(
            profile=profile, prefs=None, top_n=10,
        )

    @pytest.mark.asyncio
    async def test_handles_pipeline_exception(self):
        profile = ResumeProfile(raw_text="dev", position="Dev")

        mock_state = MagicMock()
        mock_state.load_profile.return_value = profile
        mock_state.load_preferences.return_value = None

        with (
            patch("scheduler.daily_job.get_state_manager", return_value=mock_state),
            patch("scheduler.daily_job.run_analysis_pipeline", new_callable=AsyncMock, side_effect=RuntimeError("API down")),
        ):
            from scheduler.daily_job import daily_job

            await daily_job()  # Should not raise

    @pytest.mark.asyncio
    async def test_passes_preferences_to_pipeline(self):
        profile = ResumeProfile(raw_text="dev", position="Dev")
        prefs = UserPreferences(city="Казань", salary_min=150000)
        report = DailyReport(total_found=3, top_vacancies=[], summary_text="ok")

        mock_state = MagicMock()
        mock_state.load_profile.return_value = profile
        mock_state.load_preferences.return_value = prefs

        with (
            patch("scheduler.daily_job.get_state_manager", return_value=mock_state),
            patch("scheduler.daily_job.run_analysis_pipeline", new_callable=AsyncMock, return_value=report) as mock_pipeline,
        ):
            from scheduler.daily_job import daily_job

            await daily_job()

        mock_pipeline.assert_awaited_once_with(
            profile=profile, prefs=prefs, top_n=10,
        )

    @pytest.mark.asyncio
    async def test_logs_report_stats(self):
        from datetime import UTC, datetime

        profile = ResumeProfile(raw_text="dev", position="Dev")
        vac = Vacancy(id="1", title="Dev", company="Co", city="Msk",
                       url="https://hh.ru/1", published_at=datetime.now(UTC))
        scored = [ScoredVacancy(vacancy=vac, score=0.9)]
        report = DailyReport(total_found=42, top_vacancies=scored, summary_text="ok")

        mock_state = MagicMock()
        mock_state.load_profile.return_value = profile
        mock_state.load_preferences.return_value = None

        with (
            patch("scheduler.daily_job.get_state_manager", return_value=mock_state),
            patch("scheduler.daily_job.run_analysis_pipeline", new_callable=AsyncMock, return_value=report),
        ):
            from scheduler.daily_job import daily_job

            await daily_job()
