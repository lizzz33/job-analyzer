"""
Сервис парсинга резюме из PDF/DOCX и извлечения структурированного профиля через GigaChat.
"""

from datetime import date
import json
from pathlib import Path
import re
import time

from langchain_core.prompts import PromptTemplate
from loguru import logger

from app.core.llm import GigaChatLLMFactory
from app.models.schemas import ResumeProfile

EXTRACT_PROMPT = PromptTemplate.from_template("""
Ты — HR-аналитик. Проанализируй резюме и верни JSON со следующими полями:
- name: имя кандидата
- position: желаемая должность или текущая позиция
- skills: список ключевых навыков (технических и нетехнических), массив строк
- experience_years: общий опыт работы в формате "X г. Y мес." (строка). Сегодня {current_date}. Суммируй опыт из всех мест работы. Пример: "август 2023 — н.в." при текущей дате {current_date} → "2 г. 9 мес.". Если менее года — "0 г. 5 мес.".
- education: образование одной строкой
- city: город кандидата (если указан)
- summary: краткое описание кандидата на 3-4 предложения. Пиши строго по фактам из резюме, без приукрашивания. Указывай реальные технологии и задачи, которые кандидат использовал. НЕ добавляй качества, не упомянутые в резюме (лидерство, управление командой, менторство и т.д.). Сохраняй объективный тон, без оценочных суждений вроде «сильные стороны», «владеет», «обладает опытом внедрения»

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
        self._factory = GigaChatLLMFactory()

    @property
    def llm(self):
        return self._factory.get()

    def parse(self, file_path: Path) -> ResumeProfile:
        logger.info("Parsing resume: {}", file_path.name)
        raw_text = extract_text_from_file(file_path)

        if not raw_text.strip():
            raise ValueError("Не удалось извлечь текст из файла резюме")

        # Ограничиваем длину для API
        truncated = raw_text[:8000]

        prompt = EXTRACT_PROMPT.format(
            resume_text=truncated,
            current_date=date.today().isoformat(),
        )

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.llm.invoke(prompt)
                content = response.content if hasattr(response, "content") else str(response)

                # Вытаскиваем JSON из ответа
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
                    time.sleep(wait)
                    continue
                logger.error("LLM parsing failed: {}, using raw text fallback", e)
                return ResumeProfile(
                    raw_text=raw_text,
                    summary=raw_text[:2000],
                )


resume_parser = ResumeParser()
