"""
Основной пайплайн: парсинг → embeddings → LLM-ранжирование → отчёт.
"""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json

from loguru import logger

from app.core.deps import get_feedback_store
from app.models.schemas import DailyReport, ResumeProfile, ScoredVacancy, UserPreferences, Vacancy
from app.services.hh_fetcher import QUERY_DELAY
from app.services.scorer import _normalize_semantic_scores
from app.services.seniority import (
    SeniorityLevel,
    detect_seniority_from_experience,
    detect_seniority_from_title,
    is_seniority_compatible,
)
from app.services.state_manager import (
    load_preferences,
    load_profile,
    load_search_params,
    save_last_report_vacancies,
    save_search_params,
)

# Multiply top_n by this to get the number of candidates from vector search.
SEARCH_CANDIDATES_MULTIPLIER = 3

# Feedback score adjustments — asymmetric by design: dislike penalty is stronger
# to ensure irrelevant companies sink below the min_score threshold faster.
FEEDBACK_LIKE_BOOST = 0.05
FEEDBACK_DISLIKE_PENALTY = 0.1

MIN_RELEVANCE_SCORE = 0.4
DESCRIPTION_FETCH_CONCURRENCY = 2


def _build_search_queries(profile: ResumeProfile, prefs: UserPreferences) -> list[str]:
    """Build short, focused search queries for hh.ru.

    Strategy: role + top skill combinations give the best results on hh.ru.
    Individual skills as standalone queries are too broad.
    """
    # Extract core role (first 2-3 words from position)
    role = " ".join(profile.position.split()[:3]) if profile.position else ""
    top_skills = profile.skills[:4] if profile.skills else []

    queries: list[str] = []

    # Query 1: role alone (broadest)
    if role:
        queries.append(role)

    # Queries 2-3: role + top skill (targeted)
    for skill in top_skills[:2]:
        if role:
            queries.append(f"{role} {skill}")

    # Combined top skills query (works without a role too)
    if top_skills:
        queries.append(" ".join(top_skills[:2]))

    # Queries 4+: user keywords (intentional, already short)
    if prefs.keywords:
        queries.extend(prefs.keywords[:3])

    # Fallback
    if not queries:
        queries = ["специалист", "разработчик"]

    # Deduplicate and enforce length limit
    seen: set[str] = set()
    unique = []
    for q in queries:
        key = q.lower()
        if key not in seen and len(q) <= 80:
            seen.add(key)
            unique.append(q)
    return unique


def _semantic_fallback(
    docs_with_scores: list[tuple],
    vacancies_map: dict[str, Vacancy],
    top_n: int,
) -> list[ScoredVacancy]:
    """Fallback ranking using only semantic distance when LLM is unavailable."""
    raw_distances = [d for _, d in docs_with_scores]
    norm_scores = _normalize_semantic_scores(raw_distances)

    results: list[ScoredVacancy] = []
    for (doc, _), norm in zip(docs_with_scores, norm_scores, strict=True):
        vid = doc.metadata.get("id", "")
        vacancy = vacancies_map.get(vid)
        if not vacancy:
            continue
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
        "work_formats": sorted(f.value for f in prefs.work_formats),
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

    # Fetch descriptions for vacancies without one
    new_vacancies = [v for v in vacancies_map.values() if not v.description]
    if new_vacancies:
        logger.info("Fetching descriptions for {} vacancies", len(new_vacancies))

        async def _fetch_description(v: Vacancy, sem: asyncio.Semaphore) -> None:
            async with sem:
                desc = await hh_fetcher.get_vacancy_details(v.id)
                if desc:
                    v.description = desc
                await asyncio.sleep(1.5)

        sem = asyncio.Semaphore(DESCRIPTION_FETCH_CONCURRENCY)
        await asyncio.gather(*[_fetch_description(v, sem) for v in new_vacancies])

    added = await vector_store.aadd_vacancies(list(vacancies_map.values()))
    logger.info("Added {} new vacancies to vector store", added)

    docs_with_scores = await vector_store.asearch_by_resume(
        profile, prefs=prefs, k=top_n * SEARCH_CANDIDATES_MULTIPLIER
    )

    if prefs.excluded_companies:
        ex_lower = [ex.lower() for ex in prefs.excluded_companies if ex]
        docs_with_scores = [
            (doc, score)
            for doc, score in docs_with_scores
            if not any(e in doc.metadata.get("company", "").lower() for e in ex_lower)
        ]

    # Seniority pre-filter
    candidate_level = detect_seniority_from_experience(profile.experience_years)
    if candidate_level != SeniorityLevel.UNKNOWN:
        before_seniority = len(docs_with_scores)
        docs_with_scores = [
            (doc, score)
            for doc, score in docs_with_scores
            if is_seniority_compatible(
                candidate_level, detect_seniority_from_title(doc.metadata.get("title", ""))
            )
        ]
        if len(docs_with_scores) < before_seniority:
            logger.info(
                "Seniority filter: {} → {} (candidate: {})",
                before_seniority, len(docs_with_scores), candidate_level.name,
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

    before = len(scored)
    scored = [sv for sv in scored if sv.score >= MIN_RELEVANCE_SCORE]
    if len(scored) < before:
        logger.info("Filtered {} vacancies below {:.0%} threshold", before - len(scored), MIN_RELEVANCE_SCORE)

    # Apply feedback-based score adjustments
    fb = get_feedback_store()
    liked = fb.get_liked_companies()
    disliked = fb.get_disliked_companies()
    if liked or disliked:
        for sv in scored:
            company_lower = sv.vacancy.company.lower()
            if company_lower in liked:
                sv.score = min(1.0, sv.score + FEEDBACK_LIKE_BOOST)
            elif company_lower in disliked:
                sv.score = max(0.0, sv.score - FEEDBACK_DISLIKE_PENALTY)
        scored.sort(key=lambda x: x.score, reverse=True)
        logger.info("Feedback applied: {} liked, {} disliked companies", len(liked), len(disliked))

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
