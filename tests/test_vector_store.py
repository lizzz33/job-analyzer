"""Tests for vector_store — _vacancy_to_doc, search query building, VectorStore methods."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, PropertyMock

from app.models.schemas import ResumeProfile, Vacancy


class TestVacancyToDoc:
    def test_full_vacancy(self):
        from app.services.vector_store import _vacancy_to_doc

        v = Vacancy(
            id="1",
            title="Python Dev",
            company="Yandex",
            city="Москва",
            salary_from=200000,
            salary_to=300000,
            description="Backend development",
            url="https://hh.ru/vacancy/1",
            published_at=datetime.now(UTC),
        )
        doc = _vacancy_to_doc(v)

        assert "Python Dev" in doc.page_content
        assert "Yandex" in doc.page_content
        assert "200000" in doc.page_content
        assert "300000" in doc.page_content
        assert "Backend development" in doc.page_content
        assert doc.metadata["id"] == "1"
        assert doc.metadata["title"] == "Python Dev"
        assert doc.metadata["salary_from"] == 200000

    def test_no_salary(self):
        from app.services.vector_store import _vacancy_to_doc

        v = Vacancy(
            id="2",
            title="Dev",
            company="Co",
            city="СПб",
            url="https://hh.ru/vacancy/2",
            published_at=datetime.now(UTC),
        )
        doc = _vacancy_to_doc(v)

        assert "Зарплата" not in doc.page_content

    def test_only_salary_from(self):
        from app.services.vector_store import _vacancy_to_doc

        v = Vacancy(
            id="3",
            title="Dev",
            company="Co",
            city="Msk",
            salary_from=100000,
            url="https://hh.ru/vacancy/3",
            published_at=datetime.now(UTC),
        )
        doc = _vacancy_to_doc(v)
        assert "100000" in doc.page_content
        assert "?" in doc.page_content


class TestBuildSearchQuery:
    def test_uses_position_skills_summary(self):
        from app.services.vector_store import VectorStore

        vs = VectorStore()
        profile = ResumeProfile(
            raw_text="raw",
            position="Data Engineer",
            skills=["Python", "Spark"],
            summary="Building data pipelines",
        )
        query = vs._build_search_query(profile)

        assert "Data Engineer" in query
        assert "Python" in query
        assert "data pipelines" in query

    def test_falls_back_to_raw_text(self):
        from app.services.vector_store import VectorStore

        vs = VectorStore()
        profile = ResumeProfile(raw_text="Just some raw text " * 100)
        query = vs._build_search_query(profile)

        assert query == profile.raw_text[:500]

    def test_limits_skills_to_10(self):
        from app.services.vector_store import VectorStore

        vs = VectorStore()
        profile = ResumeProfile(
            raw_text="text",
            skills=[f"skill_{i}" for i in range(20)],
        )
        query = vs._build_search_query(profile)

        assert "skill_9" in query
        assert "skill_10" not in query


class TestVectorStoreIntegration:
    """Tests that mock ChromaDB but exercise VectorStore logic."""

    def _make_store(self):
        from app.services.vector_store import VectorStore

        vs = VectorStore()

        mock_collection = MagicMock()
        mock_store = MagicMock()
        mock_store._collection = mock_collection

        # Patch the store property
        type(vs).store = PropertyMock(return_value=mock_store)

        return vs, mock_store, mock_collection

    def test_add_vacancies_skips_duplicates(self):
        vs, mock_store, mock_collection = self._make_store()
        mock_collection.get.return_value = {"ids": ["1", "2"]}

        vacancies = [
            Vacancy(id="1", title="Old", company="Co", city="Msk",
                    url="https://hh.ru/1", published_at=datetime.now(UTC)),
            Vacancy(id="3", title="New", company="Co", city="Msk",
                    url="https://hh.ru/3", published_at=datetime.now(UTC)),
        ]

        count = vs.add_vacancies(vacancies)
        assert count == 1
        mock_store.add_documents.assert_called_once()

    def test_add_vacancies_all_duplicates(self):
        vs, mock_store, mock_collection = self._make_store()
        mock_collection.get.return_value = {"ids": ["1"]}

        vacancies = [
            Vacancy(id="1", title="Old", company="Co", city="Msk",
                    url="https://hh.ru/1", published_at=datetime.now(UTC)),
        ]

        count = vs.add_vacancies(vacancies)
        assert count == 0

    def test_search_by_resume_returns_results(self):
        from langchain_core.documents import Document

        vs, mock_store, _ = self._make_store()
        doc = Document(page_content="test", metadata={"id": "1"})
        mock_store.similarity_search_with_score.return_value = [(doc, 10.0)]

        profile = ResumeProfile(raw_text="dev", position="Dev")
        results = vs.search_by_resume(profile)

        assert len(results) == 1
        assert results[0][0].metadata["id"] == "1"

    def test_search_by_resume_handles_error(self):
        vs, mock_store, _ = self._make_store()
        mock_store.similarity_search_with_score.side_effect = Exception("DB error")

        profile = ResumeProfile(raw_text="dev")
        results = vs.search_by_resume(profile)

        assert results == []

    def test_get_total_count(self):
        vs, _, mock_collection = self._make_store()
        mock_collection.count.return_value = 42

        assert vs.get_total_count() == 42

    def test_get_total_count_on_error(self):
        vs, _, mock_collection = self._make_store()
        mock_collection.count.side_effect = Exception("fail")

        assert vs.get_total_count() == 0

    def test_clear_calls_delete(self):
        vs, _, mock_collection = self._make_store()

        vs.clear()
        mock_collection.delete.assert_called_once()

    def test_get_existing_ids(self):
        vs, _, mock_collection = self._make_store()
        mock_collection.get.return_value = {"ids": ["1", "2", "3"]}

        ids = vs._get_existing_ids()
        assert ids == {"1", "2", "3"}

    def test_get_existing_ids_on_error(self):
        vs, _, mock_collection = self._make_store()
        mock_collection.get.side_effect = Exception("fail")

        assert vs._get_existing_ids() == set()
