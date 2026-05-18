from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class WorkFormat(StrEnum):
    remote = "remote"
    office = "office"
    hybrid = "hybrid"
    any_format = "any"


class UserPreferences(BaseModel):
    city: str = Field("Москва", description="Желаемый город работы")
    work_format: WorkFormat = Field(WorkFormat.any_format, description="Формат работы")
    salary_min: int | None = Field(None, description="Минимальная зарплата (руб.)")
    include_no_salary: bool = Field(False, description="Включать вакансии без указанной ЗП")
    excluded_companies: list[str] = Field(default_factory=list, description="Стоп-лист компаний")
    preferred_companies: list[str] = Field(
        default_factory=list, description="Приоритетные компании"
    )
    extra_interests: str = Field("", description="Дополнительные пожелания и интересы")
    keywords: list[str] = Field(default_factory=list, description="Ключевые слова для поиска")
    max_results_per_run: int = Field(50, description="Макс. вакансий за один парсинг")


class ResumeProfile(BaseModel):
    raw_text: str
    name: str | None = None
    position: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience_years: str | None = None  # "X г. Y мес."
    education: str | None = None
    city: str | None = None
    summary: str = ""  # LLM-generated summary for embedding


class Vacancy(BaseModel):
    id: str
    title: str
    company: str
    city: str
    salary_from: int | None = None
    salary_to: int | None = None
    currency: str = "RUR"
    work_format: str = ""
    description: str = ""
    url: str
    published_at: datetime
    source: str = "hh.ru"


class ScoredVacancy(BaseModel):
    vacancy: Vacancy
    score: float = Field(ge=0.0, le=1.0)
    match_reason: str = ""
    semantic_score: float = 0.0
    llm_score: float = 0.0


class DailyReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    total_found: int
    top_vacancies: list[ScoredVacancy]
    summary_text: str = ""
