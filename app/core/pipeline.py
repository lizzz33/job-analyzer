"""
Основной пайплайн: парсинг → embeddings → LLM-ранжирование → отчёт.
"""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json

from loguru import logger

from app.models.schemas import DailyReport, ResumeProfile, ScoredVacancy, UserPreferences, Vacancy
from app.services.hh_fetcher import QUERY_DELAY
from app.services.scorer import COSINE_DIST_BEST, COSINE_DIST_WORST
from app.services.state_manager import (
    load_preferences,
    load_profile,
    load_search_params,
    save_last_report_vacancies,
    save_search_params,
)

# Multiply top_n by this to get the number of candidates from vector search.
SEARCH_CANDIDATES_MULTIPLIER = 3


def _build_search_queries(profile: ResumeProfile, prefs: UserPreferences) -> list[str]:
    queries = []
    if profile.position:
        queries.append(profile.position)
    if prefs.keywords:
        queries.extend(prefs.keywords[:3])
    if profile.skills:
        queries.append(" ".join(profile.skills[:5]))
    if not queries:
        logger.warning(
            "No position, skills, or keywords in profile — using generic fallback queries"
        )
        queries = ["специалист", "разработчик"]
    seen: set[str] = set()
    unique = []
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


def _semantic_fallback(
    docs_with_scores: list[tuple],
    vacancies_map: dict[str, Vacancy],
    top_n: int,
) -> list[ScoredVacancy]:
    """Fallback ranking using only semantic distance when LLM is unavailable."""
    results: list[ScoredVacancy] = []
    for doc, raw_distance in docs_with_scores:
        vid = doc.metadata.get("id", "")
        vacancy = vacancies_map.get(vid)
        if not vacancy:
            continue
        norm = max(0.0, min(1.0, (COSINE_DIST_WORST - raw_distance) / (COSINE_DIST_WORST - COSINE_DIST_BEST)))
        results.append(ScoredVacancy(
            vacancy=vacancy,
            score=round(norm, 3),
            match_reason="Оценка по семантическому сходству (LLM недоступен)",
            semantic_score=round(norm, 3),
        ))
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:top_n]


async def run_analysis_pipeline(
    profile: ResumeProfile | None = None,
    prefs: UserPreferences | None = None,
    top_n: int = 10,
) -> DailyReport:
    if profile is None:
        profile = load_profile()
    if prefs is None:
        prefs = load_preferences()

    if not profile:
        raise ValueError("Резюме не загружено. Сначала загрузите резюме.")
    if not prefs:
        prefs = UserPreferences()

    queries = _build_search_queries(profile, prefs)
    logger.info("Search queries: {}", queries)

    from app.core.deps import get_hh_fetcher, get_llm_scorer, get_vector_store

    hh_fetcher = get_hh_fetcher()
    vector_store = get_vector_store()
    llm_scorer = get_llm_scorer()

    params_hash = sha256(json.dumps({
        "queries": sorted(queries),
        "city": prefs.city,
        "work_format": prefs.work_format.value,
        "salary_min": prefs.salary_min,
        "excluded": sorted(prefs.excluded_companies),
    }, sort_keys=True).encode()).hexdigest()

    saved_hash = load_search_params()
    incremental = saved_hash == params_hash
    if incremental:
        logger.info("Search params unchanged — incremental fetch")
    else:
        logger.info("Search params changed — full fetch")
        save_search_params(params_hash)

    known_ids = await vector_store._aget_existing_ids() if incremental else None

    vacancies_map: dict[str, Vacancy] = {}

    for i, query in enumerate(queries):
        vacancies = await hh_fetcher.fetch_vacancies(query, prefs, known_ids=known_ids)
        for v in vacancies:
            vacancies_map.setdefault(v.id, v)
        if i < len(queries) - 1:
            await asyncio.sleep(QUERY_DELAY)

    logger.info("Total unique vacancies fetched: {}", len(vacancies_map))

    added = await vector_store.aadd_vacancies(list(vacancies_map.values()))
    logger.info("Added {} new vacancies to vector store", added)

    docs_with_scores = await vector_store.asearch_by_resume(
        profile, k=top_n * SEARCH_CANDIDATES_MULTIPLIER
    )

    if not docs_with_scores:
        logger.warning("No results from vector search")
        return DailyReport(
            total_found=0,
            top_vacancies=[],
            summary_text="Подходящих вакансий не найдено. Попробуйте изменить ключевые слова.",
        )

    # Обогащаем карту вакансий из метаданных Chroma
    for doc, _ in docs_with_scores:
        vid = doc.metadata.get("id", "")
        if vid and vid not in vacancies_map:
            vacancies_map[vid] = Vacancy(
                id=vid,
                title=doc.metadata.get("title", ""),
                company=doc.metadata.get("company", ""),
                city=doc.metadata.get("city", ""),
                salary_from=doc.metadata.get("salary_from") or None,
                salary_to=doc.metadata.get("salary_to") or None,
                url=doc.metadata.get("url", ""),
                published_at=datetime.fromisoformat(
                    doc.metadata.get("published_at", datetime.now(UTC).isoformat())
                ),
            )

    scored = await asyncio.to_thread(
        llm_scorer.score_vacancies,
        docs_with_scores=docs_with_scores,
        vacancies_map=vacancies_map,
        profile=profile,
        prefs=prefs,
        top_n=top_n,
    )

    if not scored and docs_with_scores:
        logger.warning("LLM scoring returned nothing — falling back to semantic scores")
        scored = _semantic_fallback(docs_with_scores, vacancies_map, top_n)

    try:
        summary = await asyncio.to_thread(llm_scorer.generate_daily_summary, scored, profile)
    except Exception as e:
        logger.error("Summary generation failed: {}", e)
        summary = f"Найдено {len(scored)} подходящих вакансий (LLM summary недоступен)."
    save_last_report_vacancies([sv.model_dump(mode="json") for sv in scored])

    report = DailyReport(
        generated_at=datetime.now(UTC),
        total_found=len(vacancies_map),
        top_vacancies=scored,
        summary_text=summary,
    )

    logger.info("Pipeline complete. Top {} vacancies ranked.", len(scored))
    return report
