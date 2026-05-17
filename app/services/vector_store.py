"""
Векторное хранилище на ChromaDB.
Хранит вакансии как документы с embeddings от GigaChat.
"""

import os

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")


try:
    from chromadb.telemetry.product.posthog import Posthog

    Posthog._direct_capture = lambda self, event: None
except ImportError:
    pass

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_gigachat import GigaChatEmbeddings
from loguru import logger

from app.core.config import settings
from app.core.gigachat_auth import _get_ssl_verify, token_provider
from app.models.schemas import ResumeProfile, Vacancy


def _vacancy_to_doc(v: Vacancy) -> Document:
    salary_str = ""
    if v.salary_from or v.salary_to:
        lo = v.salary_from or "?"
        hi = v.salary_to or "?"
        salary_str = f"Зарплата: {lo}–{hi} {v.currency}."

    content = (
        f"Должность: {v.title}. "
        f"Компания: {v.company}. "
        f"Город: {v.city}. "
        f"{salary_str} "
        f"Формат: {v.work_format}. "
        f"Описание: {v.description}"
    ).strip()

    return Document(
        page_content=content,
        metadata={
            "id": v.id,
            "title": v.title,
            "company": v.company,
            "city": v.city,
            "url": v.url,
            "salary_from": v.salary_from or 0,
            "salary_to": v.salary_to or 0,
            "published_at": v.published_at.isoformat(),
        },
    )


class VectorStore:
    VACANCY_COLLECTION = "vacancies"

    def __init__(self):
        self._embeddings: GigaChatEmbeddings | None = None
        self._store: Chroma | None = None
        self._current_token: str | None = None

    def _get_embeddings(self) -> GigaChatEmbeddings:
        token = token_provider.get_token()
        if self._embeddings is None or self._current_token != token:
            self._embeddings = GigaChatEmbeddings(
                access_token=token,
                verify_ssl_certs=_get_ssl_verify(),
            )
            self._current_token = token
        return self._embeddings

    @property
    def embeddings(self) -> GigaChatEmbeddings:
        return self._get_embeddings()

    @property
    def store(self) -> Chroma:
        token = token_provider.get_token()
        if self._store is None or self._current_token != token:
            self._embeddings = self._get_embeddings()
            self._store = Chroma(
                collection_name=self.VACANCY_COLLECTION,
                embedding_function=self._embeddings,
                persist_directory=settings.chroma_db_path,
                collection_metadata={"hnsw:space": "cosine"},
            )
            self._current_token = token
        return self._store

    def add_vacancies(self, vacancies: list[Vacancy]) -> int:
        """Добавляет вакансии в хранилище, пропускает дубликаты по ID"""
        existing_ids = self._get_existing_ids()
        new_vacancies = [v for v in vacancies if v.id not in existing_ids]

        if not new_vacancies:
            logger.info("No new vacancies to add to vector store")
            return 0

        docs = [_vacancy_to_doc(v) for v in new_vacancies]
        ids = [v.id for v in new_vacancies]

        self.store.add_documents(docs, ids=ids)
        logger.info("Added {} vacancies to vector store", len(new_vacancies))
        return len(new_vacancies)

    def search_by_resume(
        self,
        profile: ResumeProfile,
        k: int = 20,
    ) -> list[tuple[Document, float]]:
        """Семантический поиск вакансий по резюме"""
        query = self._build_search_query(profile)
        logger.info("Vector search with query: {}...", query[:100])

        try:
            results = self.store.similarity_search_with_score(query, k=k)
            return results
        except Exception as e:
            logger.error("Vector search error: {}", e)
            return []

    def _build_search_query(self, profile: ResumeProfile) -> str:
        parts = []
        if profile.position:
            parts.append(profile.position)
        if profile.skills:
            parts.append(", ".join(profile.skills[:10]))
        if profile.summary:
            parts.append(profile.summary[:500])
        return " ".join(parts) or profile.raw_text[:500]

    def _get_existing_ids(self) -> set[str]:
        try:
            col = self.store._collection
            result = col.get(include=[])
            return set(result.get("ids", []))
        except Exception:
            return set()

    def get_total_count(self) -> int:
        try:
            return self.store._collection.count()
        except Exception:
            return 0

    def clear(self):
        try:
            self.store._collection.delete(where={"id": {"$ne": ""}})
            logger.info("Vector store cleared")
        except Exception as e:
            logger.error("Clear error: {}", e)


vector_store = VectorStore()
