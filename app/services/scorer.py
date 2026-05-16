"""
LLM-ранжирование вакансий через GigaChat.
Этап 2 после семантического поиска в Chroma.
"""

import json
import re

from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain_gigachat import GigaChat
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.gigachat_auth import token_provider
from app.models.schemas import ResumeProfile, ScoredVacancy, UserPreferences, Vacancy

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


class LLMScorer:
    def __init__(self):
        self._llm = None
        self._current_token = None

    @property
    def llm(self) -> GigaChat:
        token = token_provider.get_token()
        if self._llm is None or self._current_token != token:
            self._llm = GigaChat(
                access_token=token,
                verify_ssl_certs=False,
                model=settings.gigachat_model,
                temperature=0.1,
            )
            self._current_token = token
        return self._llm

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
            f"Резюме: {profile.summary[:600]}"
        )

        prompt = SCORE_PROMPT.format(
            profile=profile_str,
            city=prefs.city,
            work_format=prefs.work_format,
            salary_min=prefs.salary_min or "не указана",
            extra_interests=prefs.extra_interests or "нет",
            vacancy=vacancy_text[:1500],
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
            # Попытка вытащить score через regex как fallback
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
        Принимает результаты семантического поиска,
        прогоняет топ через LLM для финального ранжирования.
        """
        # Берём топ кандидатов из Chroma для LLM-оценки
        candidates = docs_with_scores[: min(top_n * 2, len(docs_with_scores))]
        results = []

        for doc, semantic_score in candidates:
            vid = doc.metadata.get("id", "")
            vacancy = vacancies_map.get(vid)

            # Нормализуем score (Chroma возвращает distance, меньше = лучше)
            norm_semantic = max(0.0, 1.0 - min(semantic_score, 1.0))

            try:
                llm_score, reason = self._score_one(doc.page_content, profile, prefs)
                logger.debug(f"LLM score for '{doc.metadata.get('title')}': {llm_score}")
            except Exception as e:
                logger.warning(f"LLM scoring failed for {vid}: {e}")
                llm_score = norm_semantic
                reason = "Оценка по семантическому сходству"

            combined = 0.4 * norm_semantic + 0.6 * llm_score

            if vacancy:
                results.append(
                    ScoredVacancy(
                        vacancy=vacancy,
                        score=round(combined, 3),
                        match_reason=reason,
                        semantic_score=round(norm_semantic, 3),
                        llm_score=round(llm_score, 3),
                    )
                )

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
            profile_summary=profile.summary[:500] or profile.raw_text[:500],
            vacancies_list=vac_list,
        )

        try:
            response = self.llm.invoke(prompt)
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return f"Найдено {len(scored)} подходящих вакансий."


llm_scorer = LLMScorer()
