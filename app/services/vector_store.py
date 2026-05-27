"""
Векторное хранилище на ChromaDB.
Хранит вакансии как документы с локальными embeddings (deepvk/USER-bge-m3).
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

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
    EMBED_CACHE_FILE = "embedding_cache.json"

    def __init__(self):
        self._embeddings: HuggingFaceEmbeddings | None = None
        self._store: Chroma | None = None

    @property
    def _cache_path(self) -> Path | None:
        if settings.chroma_db_path:
            return Path(settings.chroma_db_path) / self.EMBED_CACHE_FILE
        return None

    def _load_cache(self) -> dict[str, list[float]]:
        p = self._cache_path
        if p and p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {}

    def _save_cache(self, cache: dict[str, list[float]], protect_ids: set[str] | None = None) -> None:
        p = self._cache_path
        if p:
            try:
                existing = self._get_existing_ids()
                if existing:
                    protect = protect_ids or set()
                    stale = [k for k in cache if k not in existing and k not in protect]
                    for k in stale:
                        del cache[k]
                    if stale:
                        logger.debug("Pruned {} stale cache entries", len(stale))
                p.write_text(json.dumps(cache))
                logger.debug("Saved embedding cache: {} entries", len(cache))
            except Exception as e:
                logger.warning("Failed to save embedding cache: {}", e)

    def _get_embeddings(self) -> HuggingFaceEmbeddings:
        if self._embeddings is None:
            logger.info("Loading local embedding model: {}", EMBEDDING_MODEL)
            self._embeddings = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 64},
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
        """Добавляет вакансии в хранилище. Пропускает уже проэмбедженные.

        Embeddings вычисляются один раз, сохраняются в ChromaDB и кэшируются на диск.
        При повторном добавлении той же вакансии (после сброса коллекции) берёт
        embedding из дискового кэша без повторного вычисления.
        """
        existing_ids = self._get_existing_ids()
        new_vacancies = [v for v in vacancies if v.id not in existing_ids]

        if not new_vacancies:
            logger.info("No new vacancies to add to vector store")
            return 0

        docs = [_vacancy_to_doc(v) for v in new_vacancies]
        ids = [v.id for v in new_vacancies]
        texts = [d.page_content for d in docs]
        metas = [d.metadata for d in docs]

        # Load disk cache — reuse already-computed embeddings
        cache = self._load_cache()
        uncached = [(i, vid, t) for i, (vid, t) in enumerate(zip(ids, texts, strict=True)) if vid not in cache]

        if uncached:
            _, unc_ids, unc_texts = zip(*uncached, strict=True)
            emb_fn = self._get_embeddings()
            new_embs = emb_fn.embed_documents(list(unc_texts))
            for vid, emb in zip(unc_ids, new_embs, strict=True):
                cache[vid] = emb
            self._save_cache(cache, protect_ids=set(ids))
            logger.info("Computed {} embeddings ({} from cache)", len(uncached), len(ids) - len(uncached))
        else:
            logger.info("All {} embeddings loaded from cache", len(ids))

        embeddings = [cache[vid] for vid in ids]

        # Add directly with precomputed embeddings (avoids double computation)
        try:
            self.store._collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
        except Exception as e:
            if "dimension" in str(e).lower():
                logger.warning("Embedding dimension mismatch — resetting collection and retrying")
                self.reset_collection()
                self.store._collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
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
        """Семантический поиск: батч-эмбеддинг + параллельные запросы + MMR."""
        queries = self._build_search_queries(profile, prefs)
        logger.info("Vector search: {} queries, k={}", len(queries), k)
        embeddings_model = self._get_embeddings()

        # Batch-embed all queries at once
        query_embs = embeddings_model.embed_documents(queries)
        logger.info("Query embeddings computed")
        first_emb = np.array(query_embs[0], dtype=np.float32)

        col = self.store._collection

        def _query_one(emb: list[float]) -> dict:
            return col.query(query_embeddings=[emb], n_results=k, include=["documents", "metadatas", "distances"])

        # Parallel ChromaDB queries
        merged: dict[str, tuple[Document, float]] = {}
        with ThreadPoolExecutor() as pool:
            futures = {pool.submit(_query_one, emb): i for i, emb in enumerate(query_embs)}
            for future in futures:
                try:
                    qr = future.result()
                    ids_list = qr["ids"][0]
                    docs_list = qr["documents"][0]
                    metas_list = qr["metadatas"][0]
                    dists_list = qr["distances"][0]
                    for doc_text, meta, score, vid in zip(docs_list, metas_list, dists_list, ids_list, strict=True):
                        if vid not in merged or score < merged[vid][1]:
                            merged[vid] = (Document(page_content=doc_text, metadata=meta), float(score))
                except Exception as e:
                    logger.error("Vector search error: {}", e)

        results = sorted(merged.values(), key=lambda x: x[1])
        logger.info("Vector search done: {} unique results (dist range {:.4f}–{:.4f})",
                     len(results), results[0][1] if results else 0, results[-1][1] if results else 0)

        # MMR reranking for diversity
        if use_mmr and len(results) > k:
            try:
                results = self._mmr_rerank(queries[0], results, k, query_embedding=first_emb)
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

    def search_by_skills(
        self,
        skills: list[str],
        k: int = 20,
    ) -> list[tuple[Document, float]]:
        """Семантический поиск вакансий по списку навыков."""
        if not skills:
            return []
        query = ", ".join(skills[:SKILLS_IN_QUERY])
        return self.store.similarity_search_with_score(query, k=k)

    async def asearch_by_skills(
        self,
        skills: list[str],
        k: int = 20,
    ) -> list[tuple[Document, float]]:
        return await asyncio.to_thread(self.search_by_skills, skills, k=k)

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
        query_embedding: np.ndarray | None = None,
    ) -> list[tuple[Document, float]]:
        """MMR reranking: balance relevance vs diversity using stored embeddings."""
        if query_embedding is not None:
            query_emb = query_embedding
        else:
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

    def _restore_from_cache(self, ids: list[str] | None = None) -> int:
        """Restore embeddings from disk cache into ChromaDB after reset.

        If ids is None, restores all cached entries.
        Returns number of entries restored.
        """
        cache = self._load_cache()
        if not cache:
            return 0

        if ids:
            to_restore = {k: v for k, v in cache.items() if k in ids}
        else:
            to_restore = cache

        if not to_restore:
            return 0

        col = self.store._collection
        batch_ids = list(to_restore.keys())
        batch_embs = list(to_restore.values())
        col.add(ids=batch_ids, embeddings=batch_embs)
        logger.info("Restored {} embeddings from cache", len(to_restore))
        return len(to_restore)
