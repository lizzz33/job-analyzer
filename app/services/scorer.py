"""
LLM-ранжирование вакансий через GigaChat.
Этап 2 после семантического поиска в Chroma.

GigaChat API однопоточный — вызовы выполняются последовательно.
"""

import json
import re

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.llm import GigaChatLLMFactory
from app.models.schemas import ResumeProfile, ScoredVacancy, UserPreferences, Vacancy

# ChromaDB cosine distance range for similar ML vacancies.
# Observed range: ~0.10–0.20. Rescale to spread scores across [0, 1].
COSINE_DIST_BEST = 0.08
COSINE_DIST_WORST = 0.22

# Weight for combining semantic and LLM scores.
SEMANTIC_WEIGHT = 0.4
LLM_WEIGHT = 0.6

# Max candidates to pass through LLM scoring (relative to top_n).
CANDIDATES_MULTIPLIER = 2

# Text truncation limits for LLM context window.
PROFILE_SUMMARY_MAX = 600
VACANCY_TEXT_MAX = 1500
DAILY_SUMMARY_PROFILE_MAX = 500

SCORE_PROMPT = PromptTemplate.from_template("""
Ты — HR-аналитик. Оцени соответствие кандидата данной вакансии.

## Профиль кандидата:
{profile}

## Предпочтения:
- Город: {city}
- Формат работы: {work_format}
- Минимальная зарплата: {salary_min}
- Дополнительные пожелания: {extra_interests}

## Вакансия:
{vacancy}

Оцени соответствие от 0.0 до 1.0 и объясни КРАТКО (1-2 предложения).

Верни ТОЛЬКО JSON:
{{"score": 0.85, "reason": "Краткое объяснение"}}
""")


DAILY_SUMMARY_PROMPT = PromptTemplate.from_template("""
Ты — карьерный ассистент. Составь краткую сводку по подходящим вакансиям для кандидата.

## Профиль кандидата:
{profile_summary}

## Топ вакансий (по релевантности):
{vacancies_list}

Напиши дружелюбную сводку на 3-5 предложений:
- Сколько вакансий найдено и в каких областях
- Наиболее перспективные позиции
- Краткий совет

Пиши по-русски, тепло и профессионально.
""")


def _normalize_semantic_score(raw_distance: float) -> float:
    """Rescale cosine distance from [BEST, WORST] to [1.0, 0.0]."""
    return max(0.0, min(1.0, (COSINE_DIST_WORST - raw_distance) / (COSINE_DIST_WORST - COSINE_DIST_BEST)))


class LLMScorer:
    def __init__(self):
        self._factory = GigaChatLLMFactory(temperature=0.1)

    @property
    def llm(self):
        return self._factory.get()

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    def _score_one(
        self,
        vacancy_text: str,
        profile: ResumeProfile,
        prefs: UserPreferences,
    ) -> tuple[float, str]:
        profile_str = (
            f"Позиция: {profile.position or 'не указана'}\n"
            f"Навыки: {', '.join(profile.skills[:15])}\n"
            f"Опыт: {profile.experience_years or '?'}\n"
            f"Резюме: {profile.summary[:PROFILE_SUMMARY_MAX]}"
        )

        prompt = SCORE_PROMPT.format(
            profile=profile_str,
            city=prefs.city,
            work_format=prefs.work_format,
            salary_min=prefs.salary_min or "не указана",
            extra_interests=prefs.extra_interests or "нет",
            vacancy=vacancy_text[:VACANCY_TEXT_MAX],
        )

        response = self.llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return 0.5, "Не удалось оценить"

        raw = match.group()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            score_match = re.search(r'"?score"?\s*[:=]\s*([0-9]*\.?[0-9]+)', raw)
            if score_match:
                return max(0.0, min(1.0, float(score_match.group(1)))), ""
            return 0.5, "Не удалось распарсить ответ LLM"

        score = float(data.get("score", 0.5))
        reason = data.get("reason", "")
        return max(0.0, min(1.0, score)), reason

    def score_vacancies(
        self,
        docs_with_scores: list[tuple[Document, float]],
        vacancies_map: dict[str, Vacancy],
        profile: ResumeProfile,
        prefs: UserPreferences,
        top_n: int = 10,
    ) -> list[ScoredVacancy]:
        """
        Последовательное LLM-ранжирование (GigaChat API однопоточный).
        """
        candidates = docs_with_scores[: min(top_n * CANDIDATES_MULTIPLIER, len(docs_with_scores))]
        results: list[ScoredVacancy] = []

        for doc, raw_distance in candidates:
            vid = doc.metadata.get("id", "")
            vacancy = vacancies_map.get(vid)
            norm_semantic = _normalize_semantic_score(raw_distance)

            try:
                llm_score, reason = self._score_one(doc.page_content, profile, prefs)
                logger.debug("LLM score for '{}': {}", doc.metadata.get("title"), llm_score)
            except Exception as e:
                logger.warning("LLM scoring failed for {}: {}", vid, e)
                llm_score = norm_semantic
                reason = "Оценка по семантическому сходству"

            combined = SEMANTIC_WEIGHT * norm_semantic + LLM_WEIGHT * llm_score

            if vacancy:
                results.append(ScoredVacancy(
                    vacancy=vacancy,
                    score=round(combined, 3),
                    match_reason=reason,
                    semantic_score=round(norm_semantic, 3),
                    llm_score=round(llm_score, 3),
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]

    def generate_daily_summary(
        self,
        scored: list[ScoredVacancy],
        profile: ResumeProfile,
    ) -> str:
        if not scored:
            return "Сегодня подходящих вакансий не найдено."

        vac_list = "\n".join(
            f"{i + 1}. {sv.vacancy.title} в {sv.vacancy.company} "
            f"(релевантность: {int(sv.score * 100)}%) — {sv.match_reason}"
            for i, sv in enumerate(scored[:5])
        )

        prompt = DAILY_SUMMARY_PROMPT.format(
            profile_summary=profile.summary[:DAILY_SUMMARY_PROFILE_MAX] or profile.raw_text[:DAILY_SUMMARY_PROFILE_MAX],
            vacancies_list=vac_list,
        )

        try:
            response = self.llm.invoke(prompt)
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error("Summary generation failed: {}", e)
            return f"Найдено {len(scored)} подходящих вакансий."

