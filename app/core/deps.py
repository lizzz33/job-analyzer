"""
Lazy-initialized application dependencies.
Replaces module-level singletons with cached factories.
"""

from functools import lru_cache

from app.services.hh_fetcher import HHFetcher
from app.services.resume_parser import ResumeParser
from app.services.scorer import LLMScorer
from app.services.state_manager import StateManager
from app.services.vector_store import VectorStore


@lru_cache(maxsize=1)
def get_hh_fetcher() -> HHFetcher:
    return HHFetcher()


@lru_cache(maxsize=1)
def get_resume_parser() -> ResumeParser:
    return ResumeParser()


@lru_cache(maxsize=1)
def get_llm_scorer() -> LLMScorer:
    return LLMScorer()


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore()


@lru_cache(maxsize=1)
def get_state_manager() -> StateManager:
    return StateManager()


@lru_cache(maxsize=1)
def get_feedback_store():
    from app.services.feedback_store import FeedbackStore

    return FeedbackStore()


@lru_cache(maxsize=1)
def get_score_cache():
    from app.services.score_cache import ScoreCache

    return ScoreCache()
