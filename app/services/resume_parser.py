"""
Сервис парсинга резюме из PDF/DOCX и извлечения структурированного профиля через GigaChat.
"""

import asyncio
from datetime import date
import json
from pathlib import Path
import re

from langchain_core.prompts import PromptTemplate
from loguru import logger

from app.core.llm import GigaChatLLMFactory
from app.models.schemas import ResumeProfile

# Max chars sent to LLM (context window limit).
RESUME_TEXT_MAX = 8000

EXTRACT_PROMPT = PromptTemplate.from_template("""
Извлеки из резюме факты. Не домысливай, не приукрашивай, не добавляй навыки, которые явно не упоминаются.

JSON со следующими полями:
- name: имя кандидата
- position: текущая должность из последнего места работы. Если не указана — желаемая из заголовка резюме.
- skills: только навыки, которые подтверждены опытом работы или проектами. Не включай навыки «из списка ключевых навыков» без подтверждения в описании опыта. Максимум 15.
- experience_years: общий опыт работы в формате "X г. Y мес." (строка). Сегодня {current_date}. Суммируй опыт из всех мест работы. Пример: "август 2023 — н.в." при текущей дате {current_date} → "2 г. 9 мес.". Если менее года — "0 г. 5 мес.".
- education: образование одной строкой
- city: город кандидата (если указан)
- summary: 2-3 предложения. Общий профиль по всему резюме: домен, стек, уровень, специализация. Учитывай все места работы, проекты и навыки. Без оценочных слов вроде «опытный», «сильный», «уверенный».

Отвечай ТОЛЬКО валидным JSON без лишних слов.

Резюме:
{resume_text}
""")


def extract_text_from_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    elif suffix in (".docx", ".doc"):
        return extract_text_from_docx(path)
    elif suffix == ".txt":
        return path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


class ResumeParser:
    def __init__(self):
        self._factory = GigaChatLLMFactory(temperature=0)

    @property
    def llm(self):
        return self._factory.get()

    async def parse(self, file_path: Path) -> ResumeProfile:
        logger.info("Parsing resume: {}", file_path.name)
        raw_text = await asyncio.to_thread(extract_text_from_file, file_path)

        if not raw_text.strip():
            raise ValueError("Не удалось извлечь текст из файла резюме")

        truncated = raw_text[:RESUME_TEXT_MAX]

        prompt = EXTRACT_PROMPT.format(
            resume_text=truncated,
            current_date=date.today().isoformat(),
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(self.llm.invoke, prompt)
                content = response.content if hasattr(response, "content") else str(response)

                match = re.search(r"\{.*\}", content, re.DOTALL)
                if not match:
                    raise ValueError("LLM не вернул JSON")

                data = json.loads(match.group())
                profile = ResumeProfile(
                    raw_text=raw_text,
                    name=data.get("name"),
                    position=data.get("position"),
                    skills=data.get("skills", []),
                    experience_years=data.get("experience_years"),
                    education=data.get("education"),
                    city=data.get("city"),
                    summary=data.get("summary", ""),
                )
                logger.info("Resume parsed: {}, {}", profile.name, profile.position)
                return profile

            except Exception as e:
                is_rate_limit = "429" in str(e) or "Too Many Requests" in str(e)
                if is_rate_limit and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "Rate limited, retrying in {}s (attempt {}/{})", wait, attempt + 1, max_retries
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error("LLM parsing failed: {}, using raw text fallback", e)
                return ResumeProfile(
                    raw_text=raw_text,
                    summary=raw_text[:2000],
                )

