"""
LLM-ранжирование вакансий через GigaChat.
Этап 2 после семантического поиска в Chroma.

GigaChat API однопоточный — вызовы выполняются последовательно.
"""

import json
import math
import re

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.llm import GigaChatLLMFactory
from app.models.schemas import ResumeProfile, ScoredVacancy, UserPreferences, Vacancy

# Logistic calibration: semantic_score(d) = 1 / (1 + exp(a + b*d))
# Parameters fitted from 539 vacancies pairwise distribution:
#   p5=0.2782 → score 0.95, p95=0.4556 → score 0.05
# Recalibrate when DB grows significantly (run compute_calibration below).
_CALIB_A = -12.179421
_CALIB_B = 33.195479
_CALIB_FLOOR = 0.25   # d below this → score 1.0
_CALIB_CEIL = 0.58    # d above this → score 0.0

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
Оцени соответствие кандидата вакансии. Уровень кандидата — из поля «Позиция», не из лет опыта.

Кандидат:
{profile}

Пожелания кандидата:
Город: {city}. Формат: {work_formats}. Мин. ЗП: {salary_min}.
Интересы: {extra_interests}. Приоритетные компании: {preferred_companies}.
Стоп-лист: {excluded_companies}. Ключевые слова: {keywords}.

Вакансия:
{vacancy}

ЗАПРЕТЫ:
- НЕ пиши навыки кандидата как требования вакансии. В reason — только технологии из текста вакансии.
- НЕ пиши «отсутствует», пока не проверишь навыки кандидата. Docker Compose = Docker, K8s = Kubernetes.
- НЕ пиши «хорошее совпадение» и подобные фразы.
- НЕ определяй уровень по годам опыта — бери из поля «Позиция».

ОЦЕНКА:
- За каждый недостающий обязательный навык: −0.3 от максимума.
- Опыт в годах сильно не совпадает → score ≤ 0.2.
- Уровень не совпадает → −0.2. Город не совпадает → −0.3.
- ЗП ниже минимума → −0.3. Формат — второстепенно.
- Навыки в начале списка требований важнее.
- Приоритетная компания: +0.1. Совпадение с интересами: +0.05.

reason: 2 предложения. Сначала чего не хватает из требований вакансии, потом что совпадает.

Только JSON:
{{"score": 0.55, "reason": "Нет опыта с PyTorch и CV — обязательные требования вакансии. Совпадает ML-стек (CatBoost, LightGBM) и опыт с рекомендательными системами."}}
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


def _distance_to_semantic_score(d: float) -> float:
    """Convert cosine distance to semantic score via logistic calibration.

    Uses globally fitted sigmoid based on the pairwise distance distribution
    of all vacancies in the DB. Absolute scale — independent of batch composition.
    """
    if d <= _CALIB_FLOOR:
        return 1.0
    if d >= _CALIB_CEIL:
        return 0.0
    return 1.0 / (1.0 + math.exp(_CALIB_A + _CALIB_B * d))


def _normalize_semantic_scores(distances: list[float]) -> list[float]:
    """Convert raw cosine distances to absolute semantic scores."""
    if not distances:
        return []
    return [_distance_to_semantic_score(d) for d in distances]


def compute_calibration_from_db() -> None:
    """Recalibrate sigmoid parameters from current ChromaDB data.

    Run this after the DB grows significantly to update _CALIB_A, _CALIB_B.
    Prints the new constants — paste them into the module.
    """
    import os
    import shutil
    import tempfile

    import chromadb
    import numpy as np

    from app.core.config import settings

    source_db = settings.chroma_db_path or "data/chroma_db"
    db_path = os.path.join(tempfile.mkdtemp(), "db")
    shutil.copytree(source_db, db_path)
    for root, _, files in os.walk(db_path):
        for f in files:
            os.chmod(os.path.join(root, f), 0o644)

    client = chromadb.PersistentClient(path=db_path, settings=chromadb.Settings(anonymized_telemetry=False))
    col = client.get_collection("vacancies")
    data = col.get(include=["embeddings"], limit=col.count())
    embeddings = np.array(data["embeddings"], dtype=np.float32)

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / norms
    dist = 1.0 - normed @ normed.T
    triu = dist[np.triu_indices(len(embeddings), k=1)]

    p5 = float(np.percentile(triu, 5))
    p95 = float(np.percentile(triu, 95))
    pmax = float(triu.max())

    r1 = np.log(1 / 0.95 - 1)
    r2 = np.log(1 / 0.05 - 1)
    b = float((r2 - r1) / (p95 - p5))
    a = float(r1 - b * p5)

    shutil.rmtree(os.path.dirname(db_path))

    print(f"Vacancies: {len(embeddings)}, pairs: {len(triu)}")
    print(f"p5={p5:.4f}, p95={p95:.4f}, max={pmax:.4f}")
    print(f"_CALIB_A = {a:.6f}")
    print(f"_CALIB_B = {b:.6f}")
    print(f"_CALIB_FLOOR = {max(0.0, p5 - 0.03):.2f}")
    print(f"_CALIB_CEIL  = {min(1.0, pmax + 0.02):.2f}")


class LLMScorer:
    def __init__(self):
        self._factory = GigaChatLLMFactory(temperature=0.1, max_tokens=2048)

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

