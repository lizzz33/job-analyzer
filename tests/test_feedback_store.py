"""Tests for FeedbackStore."""

import pytest

from app.models.schemas import FeedbackType, VacancyFeedback
from app.services.feedback_store import FeedbackStore


@pytest.fixture
def store(tmp_path):
    return FeedbackStore(state_dir=tmp_path)


def _fb(vacancy_id="v1", feedback_type=FeedbackType.like, company="TestCorp"):
    return VacancyFeedback(vacancy_id=vacancy_id, feedback_type=feedback_type, company=company)


class TestFeedbackStore:
    def test_empty_store(self, store):
        assert store.get_all() == []
        assert store.get_liked_companies() == set()
        assert store.get_disliked_companies() == set()

    def test_add_like(self, store):
        store.add_feedback(_fb())
        liked = store.get_liked_companies()
        assert "testcorp" in liked

    def test_add_dislike(self, store):
        store.add_feedback(_fb(feedback_type=FeedbackType.dislike))
        disliked = store.get_disliked_companies()
        assert "testcorp" in disliked

    def test_remove_feedback(self, store):
        store.add_feedback(_fb())
        store.remove_feedback("v1")
        assert store.get_all() == []

    def test_overwrite_feedback(self, store):
        store.add_feedback(_fb(feedback_type=FeedbackType.like))
        store.add_feedback(_fb(feedback_type=FeedbackType.dislike))
        assert store.get_liked_companies() == set()
        assert "testcorp" in store.get_disliked_companies()

    def test_multiple_companies(self, store):
        store.add_feedback(_fb("v1", FeedbackType.like, "GoodCorp"))
        store.add_feedback(_fb("v2", FeedbackType.dislike, "BadCorp"))
        assert "goodcorp" in store.get_liked_companies()
        assert "badcorp" in store.get_disliked_companies()

    def test_company_none_excluded(self, store):
        store.add_feedback(VacancyFeedback(vacancy_id="v1", feedback_type=FeedbackType.like, company=""))
        assert store.get_liked_companies() == set()
