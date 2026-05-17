"""Tests for pipeline — query building and analysis pipeline."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import DailyReport, ResumeProfile, UserPreferences, Vacancy


class TestBuildSearchQueries:
    def test_uses_position(self):
        from app.core.pipeline import _build_search_queries

        profile = ResumeProfile(raw_text="text", position="Backend Developer")
        prefs = UserPreferences()
        queries = _build_search_queries(profile, prefs)

        assert "Backend Developer" in queries

    def test_uses_keywords(self):
        from app.core.pipeline import _build_search_queries

        profile = ResumeProfile(raw_text="text")
        prefs = UserPreferences(keywords=["python developer", "backend"])
        queries = _build_search_queries(profile, prefs)

        assert "python developer" in queries
        assert "backend" in queries

    def test_uses_skills_as_combined_query(self):
        from app.core.pipeline import _build_search_queries

        profile = ResumeProfile(raw_text="text", skills=["Python", "Django", "Docker"])
        prefs = UserPreferences()
        queries = _build_search_queries(profile, prefs)

        assert any("Python" in q for q in queries)

    def test_limits_keywords_to_3(self):
        from app.core.pipeline import _build_search_queries

        profile = ResumeProfile(raw_text="text")
        prefs = UserPreferences(keywords=["a", "b", "c", "d", "e"])
        queries = _build_search_queries(profile, prefs)

        keyword_queries = [q for q in queries if q in ["a", "b", "c", "d", "e"]]
        assert len(keyword_queries) <= 3

    def test_deduplicates_case_insensitive(self):
        from app.core.pipeline import _build_search_queries

        profile = ResumeProfile(raw_text="text", position="Python Developer")
        prefs = UserPreferences(keywords=["python developer"])
        queries = _build_search_queries(profile, prefs)

        lower = [q.lower() for q in queries]
        assert len(lower) == len(set(lower))

    def test_fallback_when_no_data(self):
        from app.core.pipeline import _build_search_queries

        profile = ResumeProfile(raw_text="text")
        prefs = UserPreferences()
        queries = _build_search_queries(profile, prefs)

        assert len(queries) > 0
        assert "специалист" in queries or "разработчик" in queries

    def test_limits_skills_to_5(self):
        from app.core.pipeline import _build_search_queries

        profile = ResumeProfile(raw_text="text", skills=[f"s{i}" for i in range(10)])
        prefs = UserPreferences()
        queries = _build_search_queries(profile, prefs)

        skills_query = [q for q in queries if "s0" in q][0]
        assert "s4" in skills_query
        assert "s5" not in skills_query


class TestRunAnalysisPipeline:
    @pytest.mark.asyncio
    async def test_raises_without_profile(self):
        from app.core.pipeline import run_analysis_pipeline

        with (
            patch("app.core.pipeline.load_profile", return_value=None),
            patch("app.core.pipeline.load_preferences", return_value=None),
            pytest.raises(ValueError, match="Резюме не загружено"),
        ):
            await run_analysis_pipeline(profile=None)

    @pytest.mark.asyncio
    async def test_returns_report_with_vacancies(self):
        from app.core.pipeline import run_analysis_pipeline

        profile = ResumeProfile(
            raw_text="dev", position="Dev", skills=["Python"], summary="Developer"
        )
        prefs = UserPreferences(city="Москва", keywords=["python"])

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_vacancies.return_value = [
            Vacancy(
                id="1", title="Python Dev", company="Co", city="Msk",
                url="https://hh.ru/1", published_at=datetime.now(UTC),
            ),
        ]

        mock_store = MagicMock()
        mock_store._get_existing_ids.return_value = set()
        mock_store.add_vacancies.return_value = 1
        mock_store.search_by_resume.return_value = []  # empty → "no results" path

        mock_scorer = MagicMock()
        mock_scorer.generate_daily_summary.return_value = "No results"

        with (
            patch("app.core.pipeline.hh_fetcher", mock_fetcher),
            patch("app.core.pipeline.vector_store", mock_store),
            patch("app.core.pipeline.llm_scorer", mock_scorer),
            patch("app.core.pipeline.load_profile", return_value=None),
            patch("app.core.pipeline.load_preferences", return_value=None),
            patch("app.core.pipeline.load_search_params", return_value=None),
            patch("app.core.pipeline.save_search_params"),
            patch("app.core.pipeline.save_last_report_vacancies"),
        ):
            report = await run_analysis_pipeline(profile=profile, prefs=prefs)

        # Vacancies were fetched but vector search returned nothing → early return
        assert isinstance(report, DailyReport)
        assert report.total_found == 0  # early return sets total_found=0
        assert "не найдено" in report.summary_text.lower()

    @pytest.mark.asyncio
    async def test_returns_report_with_scored_vacancies(self):
        from langchain_core.documents import Document

        from app.core.pipeline import run_analysis_pipeline
        from app.models.schemas import ScoredVacancy

        profile = ResumeProfile(
            raw_text="dev", position="Dev", skills=["Python"], summary="Developer"
        )
        prefs = UserPreferences(city="Москва", keywords=["python"])

        vacancy = Vacancy(
            id="1", title="Python Dev", company="Co", city="Msk",
            url="https://hh.ru/1", published_at=datetime.now(UTC),
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_vacancies.return_value = [vacancy]

        doc = Document(page_content="Python Dev at Co", metadata={
            "id": "1", "title": "Python Dev", "company": "Co", "city": "Msk",
            "url": "https://hh.ru/1",
            "published_at": datetime.now(UTC).isoformat(),
        })

        scored_vac = ScoredVacancy(
            vacancy=vacancy, score=0.9, match_reason="Great match"
        )

        mock_store = MagicMock()
        mock_store._get_existing_ids.return_value = set()
        mock_store.add_vacancies.return_value = 1
        mock_store.search_by_resume.return_value = [(doc, 10.0)]

        mock_scorer = MagicMock()
        mock_scorer.score_vacancies.return_value = [scored_vac]
        mock_scorer.generate_daily_summary.return_value = "Great results"

        with (
            patch("app.core.pipeline.hh_fetcher", mock_fetcher),
            patch("app.core.pipeline.vector_store", mock_store),
            patch("app.core.pipeline.llm_scorer", mock_scorer),
            patch("app.core.pipeline.load_profile", return_value=None),
            patch("app.core.pipeline.load_preferences", return_value=None),
            patch("app.core.pipeline.load_search_params", return_value=None),
            patch("app.core.pipeline.save_search_params"),
            patch("app.core.pipeline.save_last_report_vacancies"),
        ):
            report = await run_analysis_pipeline(profile=profile, prefs=prefs)

        assert isinstance(report, DailyReport)
        assert report.total_found == 1
        assert report.summary_text == "Great results"
        assert len(report.top_vacancies) == 1

    @pytest.mark.asyncio
    async def test_incremental_fetch_when_params_unchanged(self):
        from app.core.pipeline import run_analysis_pipeline

        profile = ResumeProfile(raw_text="dev", position="Dev", skills=["Python"])
        prefs = UserPreferences(city="Москва")

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_vacancies.return_value = []

        mock_store = MagicMock()
        mock_store._get_existing_ids.return_value = set()
        mock_store.add_vacancies.return_value = 0
        mock_store.search_by_resume.return_value = []

        mock_scorer = MagicMock()
        mock_scorer.generate_daily_summary.return_value = "Empty"

        with (
            patch("app.core.pipeline.hh_fetcher", mock_fetcher),
            patch("app.core.pipeline.vector_store", mock_store),
            patch("app.core.pipeline.llm_scorer", mock_scorer),
            patch("app.core.pipeline.load_profile", return_value=None),
            patch("app.core.pipeline.load_preferences", return_value=None),
            patch("app.core.pipeline.load_search_params", return_value="same_hash"),
            patch("app.core.pipeline.save_search_params"),
            patch("app.core.pipeline.save_last_report_vacancies"),
            patch("app.core.pipeline.sha256") as mock_hash,
        ):
            mock_hash.return_value.hexdigest.return_value = "same_hash"
            await run_analysis_pipeline(profile=profile, prefs=prefs)

        call_args = mock_fetcher.fetch_vacancies.call_args
        known_ids = call_args.kwargs.get("known_ids")
        if known_ids is None and len(call_args.args) >= 3:
            known_ids = call_args.args[2]
        assert known_ids is not None
