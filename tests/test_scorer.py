"""Tests for LLM scorer — score parsing, combination logic, daily summary."""

from datetime import UTC, datetime
import json
from unittest.mock import MagicMock, PropertyMock

from langchain_core.documents import Document

from app.models.schemas import (
    ResumeProfile,
    ScoredVacancy,
    UserPreferences,
    Vacancy,
)


def _make_vacancy(vid="1", title="Dev") -> Vacancy:
    return Vacancy(
        id=vid,
        title=title,
        company="Co",
        city="MSK",
        url=f"https://hh.ru/vacancy/{vid}",
        published_at=datetime.now(UTC),
    )


def _make_doc(vacancy_id="1", title="Dev", content="Python developer role"):
    return Document(
        page_content=content,
        metadata={"id": vacancy_id, "title": title, "company": "Co", "city": "MSK"},
    )


def _make_scorer_with_llm(llm_content: str):
    """Create LLMScorer with mocked LLM property."""
    from app.services.scorer import LLMScorer

    scorer = LLMScorer()
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = llm_content
    mock_llm.invoke.return_value = mock_resp
    type(scorer).llm = PropertyMock(return_value=mock_llm)
    return scorer


class TestScoreOne:
    def test_score_one_parses_json(self):
        scorer = _make_scorer_with_llm('{"score": 0.9, "reason": "Good match"}')

        profile = ResumeProfile(raw_text="dev", position="Dev", skills=["Python"])
        prefs = UserPreferences(city="Москва")
        score, reason = scorer._score_one("Python developer", profile, prefs)

        assert score == 0.9
        assert reason == "Good match"

    def test_score_one_clamps_high_score(self):
        scorer = _make_scorer_with_llm('{"score": 1.5, "reason": "Over"}')

        profile = ResumeProfile(raw_text="dev")
        prefs = UserPreferences()
        score, reason = scorer._score_one("text", profile, prefs)

        assert score == 1.0

    def test_score_one_clamps_negative_score(self):
        scorer = _make_scorer_with_llm('{"score": -0.5, "reason": "Bad"}')

        profile = ResumeProfile(raw_text="dev")
        prefs = UserPreferences()
        score, _ = scorer._score_one("text", profile, prefs)

        assert score == 0.0

    def test_score_one_no_json_returns_default(self):
        scorer = _make_scorer_with_llm("No JSON here")

        profile = ResumeProfile(raw_text="dev")
        prefs = UserPreferences()
        score, reason = scorer._score_one("text", profile, prefs)

        assert score == 0.5
        assert "Не удалось оценить" in reason

    def test_score_one_malformed_json_with_score_regex(self):
        # Has braces so regex matches, but invalid JSON → falls back to score regex
        scorer = _make_scorer_with_llm('{"score": 0.75, reason: ok}')

        profile = ResumeProfile(raw_text="dev")
        prefs = UserPreferences()
        score, reason = scorer._score_one("text", profile, prefs)

        assert score == 0.75

    def test_score_one_completely_broken_json(self):
        scorer = _make_scorer_with_llm("{not valid json at all}")

        profile = ResumeProfile(raw_text="dev")
        prefs = UserPreferences()
        score, reason = scorer._score_one("text", profile, prefs)

        assert score == 0.5


class TestScoreVacancies:
    def _make_scorer(self, llm_score=0.8, llm_reason="Match"):
        return _make_scorer_with_llm(
            json.dumps({"score": llm_score, "reason": llm_reason})
        )

    def test_returns_scored_vacancies_sorted(self):
        scorer = self._make_scorer()

        profile = ResumeProfile(raw_text="dev", position="Dev", skills=["Python"])
        prefs = UserPreferences(city="Москва")

        doc1 = _make_doc("1", "Dev", "Python role")
        doc2 = _make_doc("2", "ML", "ML role")
        vacancies_map = {"1": _make_vacancy("1"), "2": _make_vacancy("2")}

        docs = [(doc1, 10.0), (doc2, 12.0)]
        results = scorer.score_vacancies(docs, vacancies_map, profile, prefs, top_n=5)

        assert len(results) == 2
        assert all(isinstance(r, ScoredVacancy) for r in results)
        assert results[0].score >= results[1].score

    def test_respects_top_n(self):
        scorer = self._make_scorer()

        profile = ResumeProfile(raw_text="dev", skills=["Python"])
        prefs = UserPreferences()

        docs = [(_make_doc(str(i)), 10.0) for i in range(10)]
        vacancies_map = {str(i): _make_vacancy(str(i)) for i in range(10)}

        results = scorer.score_vacancies(docs, vacancies_map, profile, prefs, top_n=3)

        assert len(results) == 3

    def test_skips_vacancy_not_in_map(self):
        scorer = self._make_scorer()

        profile = ResumeProfile(raw_text="dev")
        prefs = UserPreferences()

        doc = _make_doc("missing_id")
        docs = [(doc, 10.0)]
        vacancies_map = {}

        results = scorer.score_vacancies(docs, vacancies_map, profile, prefs)

        assert len(results) == 0

    def test_llm_failure_falls_back_to_semantic(self):
        from app.services.scorer import LLMScorer

        scorer = LLMScorer()
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("API error")
        type(scorer).llm = PropertyMock(return_value=mock_llm)

        profile = ResumeProfile(raw_text="dev", position="Dev")
        prefs = UserPreferences()

        doc = _make_doc("1")
        vacancies_map = {"1": _make_vacancy("1")}
        docs = [(doc, 10.0)]

        results = scorer.score_vacancies(docs, vacancies_map, profile, prefs)

        assert len(results) == 1
        assert results[0].match_reason == "Оценка по семантическому сходству"


class TestDailySummary:
    def test_empty_scored_returns_default_message(self):
        from app.services.scorer import LLMScorer

        scorer = LLMScorer()
        profile = ResumeProfile(raw_text="dev")

        result = scorer.generate_daily_summary([], profile)
        assert "не найдено" in result.lower()

    def test_summary_calls_llm(self):
        from app.services.scorer import LLMScorer

        scorer = LLMScorer()
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = "Найдено несколько вакансий."
        mock_llm.invoke.return_value = mock_resp
        type(scorer).llm = PropertyMock(return_value=mock_llm)

        vacancy = _make_vacancy("1", "Python Dev")
        scored = [
            ScoredVacancy(vacancy=vacancy, score=0.9, match_reason="Great match"),
        ]
        profile = ResumeProfile(raw_text="dev", summary="Experienced developer")

        result = scorer.generate_daily_summary(scored, profile)
        assert "вакансий" in result.lower() or "вакансии" in result.lower()
        mock_llm.invoke.assert_called_once()

    def test_summary_llm_failure_returns_fallback(self):
        from app.services.scorer import LLMScorer

        scorer = LLMScorer()
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM down")
        type(scorer).llm = PropertyMock(return_value=mock_llm)

        vacancy = _make_vacancy("1")
        scored = [ScoredVacancy(vacancy=vacancy, score=0.5)]
        profile = ResumeProfile(raw_text="dev")

        result = scorer.generate_daily_summary(scored, profile)
        assert "1" in result
