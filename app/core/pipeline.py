"""
Основной пайплайн: парсинг → embeddings → LLM-ранжирование → отчёт.
"""

from datetime import datetime

from loguru import logger

from app.models.schemas import DailyReport, ResumeProfile, UserPreferences, Vacancy
from app.services.hh_fetcher import hh_fetcher
from app.services.scorer import llm_scorer
from app.services.state_manager import (
    load_preferences,
    load_profile,
    save_last_report_vacancies,
)
from app.services.vector_store import vector_store


def _build_search_queries(profile: ResumeProfile, prefs: UserPreferences) -> list[str]:
    queries = []
    if profile.position:
        queries.append(profile.position)
    if prefs.keywords:
        queries.extend(prefs.keywords[:3])
    if profile.skills:
        queries.append(" ".join(profile.skills[:5]))
    if not queries:
        queries = ["специалист", "разработчик"]
    return list(dict.fromkeys(queries))


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
    logger.info(f"Search queries: {queries}")

    all_vacancies: list[Vacancy] = []
    vacancies_map: dict[str, Vacancy] = {}

    for query in queries:
        vacancies = await hh_fetcher.fetch_vacancies(query, prefs)
        for v in vacancies:
            if v.id not in vacancies_map:
                vacancies_map[v.id] = v
                all_vacancies.append(v)

    logger.info(f"Total unique vacancies fetched: {len(all_vacancies)}")

    added = vector_store.add_vacancies(all_vacancies)
    logger.info(f"Added {added} new vacancies to vector store")

    docs_with_scores = vector_store.search_by_resume(profile, k=top_n * 3)

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
                    doc.metadata.get("published_at", datetime.utcnow().isoformat())
                ),
            )

    scored = llm_scorer.score_vacancies(
        docs_with_scores=docs_with_scores,
        vacancies_map=vacancies_map,
        profile=profile,
        prefs=prefs,
        top_n=top_n,
    )

    summary = llm_scorer.generate_daily_summary(scored, profile)
    save_last_report_vacancies([sv.model_dump(mode="json") for sv in scored])

    report = DailyReport(
        generated_at=datetime.utcnow(),
        total_found=len(all_vacancies),
        top_vacancies=scored,
        summary_text=summary,
    )

    logger.info(f"Pipeline complete. Top {len(scored)} vacancies ranked.")
    return report
