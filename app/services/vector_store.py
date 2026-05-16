"""
Векторное хранилище на ChromaDB.
Хранит вакансии как документы с embeddings от GigaChat.
"""

import os

os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"


import chromadb

# posthog >= 7 changed capture() signature, breaking chromadb 0.6.3 telemetry.
# Patch _direct_capture to no-op so posthog.capture is never called.
from chromadb.telemetry.product.posthog import Posthog

Posthog._direct_capture = lambda self, event: None

from langchain.schema import Document
from langchain_chroma import Chroma
from langchain_gigachat import GigaChatEmbeddings
from loguru import logger

from app.core.config import settings
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
        self._embeddings = None
        self._store = None
        self._client = None

    def _make_embeddings(self) -> GigaChatEmbeddings:
        from app.core.gigachat_auth import token_provider
        return GigaChatEmbeddings(
            access_token=token_provider.get_token(),
            verify_ssl_certs=False,
        )

    @property
    def embeddings(self) -> GigaChatEmbeddings:
        if self._embeddings is None:
            self._embeddings = self._make_embeddings()
        return self._embeddings

    @property
    def store(self) -> Chroma:
        if self._store is None:
            self._embeddings = self._make_embeddings()
            self._store = Chroma(
                collection_name=self.VACANCY_COLLECTION,
                embedding_function=self._embeddings,
                persist_directory=settings.chroma_db_path,
            )
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
        logger.info(f"Added {len(new_vacancies)} vacancies to vector store")
        return len(new_vacancies)

    def search_by_resume(
        self,
        profile: ResumeProfile,
        k: int = 20,
    ) -> list[tuple[Document, float]]:
        """Семантический поиск вакансий по резюме"""
        query = self._build_search_query(profile)
        logger.info(f"Vector search with query: {query[:100]}...")

        try:
            results = self.store.similarity_search_with_score(query, k=k)
            return results
        except Exception as e:
            logger.error(f"Vector search error: {e}")
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
            logger.error(f"Clear error: {e}")


vector_store = VectorStore()
