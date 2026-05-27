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

# Min-max normalization bounds are derived from the actual search batch,
# so no hardcoded distance constants are needed.

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
Ты — строгий рекрутер. Оцени РЕАЛЬНОЕ соответствие кандидата вакансии.

Кандидат:
{profile}

Пожелания кандидата:
- Город: {city}
- Формат работы: {work_formats}
- Минимальная зарплата: {salary_min}
- Интересы: {extra_interests}
- Приоритетные компании: {preferred_companies}
- Стоп-лист компаний: {excluded_companies}
- Ключевые слова: {keywords}

Вакансия:
{vacancy}

ПРАВИЛА ОЦЕНКИ:
- Главное — совпадение описания вакансии с опытом и навыками кандидата.
- Оценивай стек технологий, задачи, домен, уровень ответственности.
- Требования по опыту не совпадают (например, вакансия senior, а кандидат junior) → ниже 0.3
- Сфера вакансии не связана с опытом кандидата → ниже 0.3
- Город не совпадает → ниже 0.5. Район или станция метро того же города — это совпадение.
- Зарплата ниже минимума → ниже 0.5
- Формат работы — второстепенный фактор, не занижай оценку только из-за формата.
- Компания в приоритетных → +0.1
- НЕ пиши «идеально» — это почти никогда не правда.
- Оценка 0.8+ только если есть реальное совпадение по описанию и навыкам.
- Если кандидат не подходит — ставь score < 0.4 и пиши причину отказа в reason.

В reason напиши 1-3 предложения: сначала почему подходит, затем несовпадения на что обратить внимание.

Ответ — ТОЛЬКО JSON:
{{"score": 0.75, "reason": "Хорошее совпадение по ML-стеку: CatBoost, LightGBM, FastAPI — всё из опыта кандидата. Компания из приоритетных. Вакансия без указания ЗП."}}
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


def _normalize_semantic_scores(distances: list[float]) -> list[float]:
    """Min-max normalize raw cosine distances within the batch to [1.0, 0.0].

    Best (lowest) distance → 1.0, worst (highest) → 0.0.
    Single result or all-equal distances → 0.5 for every item.
    """
    n = len(distances)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    min_d = min(distances)
    max_d = max(distances)
    span = max_d - min_d
    if span < 1e-9:
        return [0.5] * n
    return [max(0.0, min(1.0, (max_d - d) / span)) for d in distances]


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
            work_formats=", ".join(f.value for f in prefs.work_formats) or "любой",
            salary_min=prefs.salary_min or "не указана",
            extra_interests=prefs.extra_interests or "нет",
            preferred_companies=", ".join(prefs.preferred_companies) or "нет",
            excluded_companies=", ".join(prefs.excluded_companies) or "нет",
            keywords=", ".join(prefs.keywords) or "нет",
            vacancy=vacancy_text[:VACANCY_TEXT_MAX],
        )

        response = self.llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Strip markdown code blocks
        content = re.sub(r"```(?:json)?\s*", "", content).strip()

        # Try direct JSON parse first
        try:
            data = json.loads(content)
            score = float(data.get("score", 0.5))
            reason = str(data.get("reason", ""))
            return max(0.0, min(1.0, score)), reason
        except (json.JSONDecodeError, ValueError):
            pass

        # Find first balanced { } block
        start = content.find("{")
        if start == -1:
            return 0.5, "Не удалось оценить"
        depth = 0
        end = start
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        raw = content[start:end]

        try:
            data = json.loads(raw)
            score = float(data.get("score", 0.5))
            reason = str(data.get("reason", ""))
            return max(0.0, min(1.0, score)), reason
        except (json.JSONDecodeError, ValueError):
            pass

        # Last resort: extract score and reason separately
        score_match = re.search(r'"?score"?\s*[:=]\s*([0-9]*\.?[0-9]+)', content)
        reason_match = re.search(r'"?reason"?\s*[:=]\s*"([^"]*)"', content)
        score = float(score_match.group(1)) if score_match else 0.5
        reason = reason_match.group(1) if reason_match else ""
        return max(0.0, min(1.0, score)), reason

    def score_vacancies(
        self,
        docs_with_scores: list[tuple[Document, float]],
        vacancies_map: dict[str, Vacancy],
        profile: ResumeProfile,
        prefs: UserPreferences,
        top_n: int = 10,
    ) -> list[ScoredVacancy]:
        """LLM-ранжирование с кэшированием оценок."""
        from app.core.deps import get_score_cache

        cache = get_score_cache()
        candidates = docs_with_scores[: min(top_n * CANDIDATES_MULTIPLIER, len(docs_with_scores))]
        results: list[ScoredVacancy] = []

        raw_distances = [d for _, d in candidates]
        norm_semantics = _normalize_semantic_scores(raw_distances)

        for (doc, _raw_distance), norm_semantic in zip(candidates, norm_semantics, strict=True):
            vid = doc.metadata.get("id", "")
            vacancy = vacancies_map.get(vid)

            c_hash = cache.content_hash(doc.page_content, profile.position or "")
            cached = cache.get(vid, c_hash)
            if cached:
                llm_score = cached["llm_score"]
                reason = cached["reason"]
                logger.debug("Cache hit for '{}'", doc.metadata.get("title"))
            else:
                try:
                    llm_score, reason = self._score_one(doc.page_content, profile, prefs)
                    logger.debug("LLM score for '{}': {}", doc.metadata.get("title"), llm_score)
                except Exception as e:
                    logger.warning("LLM scoring failed for {}: {}", vid, e)
                    llm_score = norm_semantic
                    reason = "Оценка по семантическому сходству"

                cache.put(vid, {
                    "llm_score": llm_score,
                    "reason": reason,
                    "content_hash": c_hash,
                })

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

