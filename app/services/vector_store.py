"""
Векторное хранилище на ChromaDB.
Хранит вакансии как документы с локальными embeddings (deepvk/USER-bge-m3).
"""

import asyncio
import os

os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_DISABLED"] = "1"

import chromadb

# Suppress chromadb telemetry bug (capture() signature mismatch in 0.6.x)
try:
    import chromadb.telemetry.events as _te
    _te.capture = lambda *a, **kw: None  # type: ignore[attr-defined]
except Exception:
    pass
from langchain_chroma import Chroma
from langchain_chroma.vectorstores import maximal_marginal_relevance
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from loguru import logger
import numpy as np

from app.core.config import settings
from app.models.schemas import ResumeProfile, UserPreferences, Vacancy

EMBEDDING_MODEL = "deepvk/USER-bge-m3"

SKILLS_IN_QUERY = 10
QUERY_SUMMARY_MAX = 500


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

    metadata: dict = {
        "id": v.id,
        "title": v.title,
        "company": v.company,
        "city": v.city,
        "url": v.url,
        "published_at": v.published_at.isoformat(),
    }
    if v.salary_from is not None:
        metadata["salary_from"] = v.salary_from
    if v.salary_to is not None:
        metadata["salary_to"] = v.salary_to

    return Document(
        page_content=content,
        metadata=metadata,
    )


class VectorStore:
    VACANCY_COLLECTION = "vacancies"

    def __init__(self):
        self._embeddings: HuggingFaceEmbeddings | None = None
        self._store: Chroma | None = None

    def _get_embeddings(self) -> HuggingFaceEmbeddings:
        if self._embeddings is None:
            logger.info("Loading local embedding model: {}", EMBEDDING_MODEL)
            self._embeddings = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
            logger.info("Embedding model loaded")
        return self._embeddings

    @property
    def embeddings(self) -> HuggingFaceEmbeddings:
        return self._get_embeddings()

    @property
    def store(self) -> Chroma:
        if self._store is None:
            client_settings = chromadb.Settings(anonymized_telemetry=False)
            kwargs: dict = {
                "collection_name": self.VACANCY_COLLECTION,
                "embedding_function": self._get_embeddings(),
                "collection_metadata": {"hnsw:space": "cosine"},
                "client_settings": client_settings,
            }
            if settings.chroma_db_path:
                kwargs["persist_directory"] = settings.chroma_db_path
            self._store = Chroma(**kwargs)
        return self._store

    def ensure_compatible(self):
        """Reset collection if embedding dimension changed (e.g. switched from GigaChat to local)."""
        try:
            count = self.store._collection.count()
            if count == 0:
                return
            sample = self.store._collection.get(limit=1, include=["embeddings"])
            embeddings = sample.get("embeddings")
            if embeddings is None or len(embeddings) == 0 or len(embeddings[0]) == 0:
                return
            stored_dim = len(sample["embeddings"][0])
            test_emb = self._get_embeddings().embed_query("test")
            model_dim = len(test_emb)
            if stored_dim != model_dim:
                logger.warning(
                    "Embedding dimension mismatch (stored={}, model={}) — resetting collection",
                    stored_dim, model_dim,
                )
                self.reset_collection()
        except Exception as e:
            logger.warning("Compatibility check failed: {}", e)

    def add_vacancies(self, vacancies: list[Vacancy]) -> int:
        """Добавляет вакансии в хранилище, обновляет существующие если появилось описание"""
        existing_ids = self._get_existing_ids()
        new_vacancies = [v for v in vacancies if v.id not in existing_ids]
        to_update = [v for v in vacancies if v.id in existing_ids and v.description]

        if to_update:
            docs = [_vacancy_to_doc(v) for v in to_update]
            try:
                self.store.add_documents(docs, ids=[v.id for v in to_update])
                logger.info("Updated {} existing vacancies with descriptions", len(to_update))
            except Exception as e:
                logger.warning("Failed to update existing vacancies: {}", e)

        if not new_vacancies:
            logger.info("No new vacancies to add to vector store")
            return 0

        docs = [_vacancy_to_doc(v) for v in new_vacancies]
        ids = [v.id for v in new_vacancies]

        try:
            self.store.add_documents(docs, ids=ids)
        except Exception as e:
            if "dimension" in str(e).lower():
                logger.warning("Embedding dimension mismatch — resetting collection and retrying")
                self.reset_collection()
                self.store.add_documents(docs, ids=ids)
            else:
                raise

        logger.info("Added {} vacancies to vector store", len(new_vacancies))
        return len(new_vacancies)

    async def aadd_vacancies(self, vacancies: list[Vacancy]) -> int:
        return await asyncio.to_thread(self.add_vacancies, vacancies)

    def search_by_resume(
        self,
        profile: ResumeProfile,
        prefs: UserPreferences | None = None,
        k: int = 20,
        use_mmr: bool = True,
    ) -> list[tuple[Document, float]]:
        """Семантический поиск: мульти-запросы + опциональный MMR для разнообразия."""
        queries = self._build_search_queries(profile, prefs)

        # Multi-query: run each query, merge by best score per vacancy
        merged: dict[str, tuple[Document, float]] = {}
        for query in queries:
            logger.info("Vector search: {}...", query[:100])
            try:
                results = self.store.similarity_search_with_score(query, k=k)
            except Exception as e:
                logger.error("Vector search error: {}", e)
                continue
            for doc, score in results:
                vid = doc.metadata.get("id", "")
                if vid not in merged or score < merged[vid][1]:
                    merged[vid] = (doc, score)

        results = sorted(merged.values(), key=lambda x: x[1])

        # MMR reranking for diversity
        if use_mmr and len(results) > k:
            try:
                results = self._mmr_rerank(queries[0], results, k)
            except Exception as e:
                logger.warning("MMR rerank failed, using top-k: {}", e)
                results = results[:k]

        return results

    async def asearch_by_resume(
        self,
        profile: ResumeProfile,
        prefs: UserPreferences | None = None,
        k: int = 20,
        use_mmr: bool = True,
    ) -> list[tuple[Document, float]]:
        return await asyncio.to_thread(self.search_by_resume, profile, prefs, k=k, use_mmr=use_mmr)

    def _build_search_queries(
        self,
        profile: ResumeProfile,
        prefs: UserPreferences | None = None,
    ) -> list[str]:
        queries = []
        # Role + summary
        if profile.position:
            role_q = profile.position
            if profile.summary:
                role_q += " " + profile.summary[:200]
            queries.append(role_q)
        # Skills
        if profile.skills:
            queries.append(", ".join(profile.skills[:SKILLS_IN_QUERY]))
        # Domain / keywords / interests
        domain_parts = []
        if prefs:
            if prefs.extra_interests:
                domain_parts.append(prefs.extra_interests)
            if prefs.keywords:
                domain_parts.append(", ".join(prefs.keywords[:5]))
        if domain_parts:
            queries.append(" ".join(domain_parts))
        if not queries:
            queries.append(profile.raw_text[:QUERY_SUMMARY_MAX])
        return queries

    def _mmr_rerank(
        self,
        query_text: str,
        candidates: list[tuple[Document, float]],
        k: int,
        lambda_mult: float = 0.7,
    ) -> list[tuple[Document, float]]:
        """MMR reranking: balance relevance vs diversity using stored embeddings."""
        query_emb = np.array(self._get_embeddings().embed_query(query_text), dtype=np.float32)

        ids = [doc.metadata.get("id", "") for doc, _ in candidates]
        stored = self.store._collection.get(ids=ids, include=["embeddings"])
        emb_map = {vid: np.array(emb, dtype=np.float32) for vid, emb in zip(stored["ids"], stored["embeddings"], strict=True)}

        doc_embs = []
        valid_indices = []
        for i, (doc, _) in enumerate(candidates):
            emb = emb_map.get(doc.metadata.get("id", ""))
            if emb is not None:
                doc_embs.append(emb)
                valid_indices.append(i)

        if not doc_embs:
            return candidates[:k]

        doc_embs = np.array(doc_embs)

        # MMR selection
        mmr_idx = maximal_marginal_relevance(query_emb, doc_embs, lambda_mult=lambda_mult, k=min(k, len(doc_embs)))
        return [candidates[valid_indices[i]] for i in mmr_idx]

    def _get_existing_ids(self) -> set[str]:
        try:
            col = self._store._collection if self._store else None
            if col is None:
                col = self.store._collection
            result = col.get(include=[])
            return set(result.get("ids", []))
        except Exception:
            return set()

    async def _aget_existing_ids(self) -> set[str]:
        return await asyncio.to_thread(self._get_existing_ids)

    def get_total_count(self) -> int:
        try:
            return self.store._collection.count()
        except Exception as e:
            logger.warning("get_total_count error: {}", e)
            return 0

    def clear(self):
        self.reset_collection()
        logger.info("Vector store cleared")

    def reset_collection(self):
        """Drop and recreate the collection (needed when embedding model changes)."""
        try:
            client = self.store._client
            client.delete_collection(self.VACANCY_COLLECTION)
            self._store = None
            logger.info("Collection reset — will recreate on next access")
        except Exception as e:
            logger.error("Reset collection error: {}", e)
