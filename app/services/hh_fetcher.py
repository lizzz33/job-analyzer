"""
Получение вакансий через парсинг страниц hh.ru.
HH.ru закрыл публичный API, поэтому парсим HTML.
"""

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup, Tag
from loguru import logger

from app.models.schemas import UserPreferences, Vacancy, WorkFormat

HH_SEARCH_URL = "https://hh.ru/search/vacancy"
HH_VACANCY_URL = "https://hh.ru/vacancy"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CITY_AREA_MAP = {
    "москва": 1,
    "санкт-петербург": 2,
    "спб": 2,
    "екатеринбург": 3,
    "новосибирск": 4,
    "казань": 88,
    "нижний новгород": 66,
    "челябинск": 104,
    "ростов-на-дону": 76,
    "уфа": 99,
    "самара": 78,
    "краснодар": 53,
    "удалённо": 113,
    "удаленно": 113,
    "remote": 113,
    "россия": 113,
}

SCHEDULE_MAP = {
    WorkFormat.remote: "remote",
    WorkFormat.office: "fullDay",
    WorkFormat.hybrid: "flyInFlyOut",
    WorkFormat.any: None,
}

CURRENCY_MAP = {"₽": "RUR", "$": "USD", "€": "EUR", "руб": "RUR"}


def _parse_salary(text: str) -> tuple[int | None, int | None, str]:
    """Parse salary text like 'от 200 000 ₽', 'до 4 000 $', '100 000 — 200 000 ₽'."""
    text = text.replace("\xa0", " ").replace(" ", " ").replace("−", "—")

    currency = "RUR"
    for symbol, code in CURRENCY_MAP.items():
        if symbol in text:
            currency = code
            break

    # "100 000 — 200 000"
    range_match = re.search(r"([\d\s]+)\s*—\s*([\d\s]+)", text)
    if range_match:
        sal_from = int(range_match.group(1).replace(" ", ""))
        sal_to = int(range_match.group(2).replace(" ", ""))
        return sal_from, sal_to, currency

    # "от 200 000"
    from_match = re.search(r"от\s+([\d\s]+)", text)
    if from_match:
        return int(from_match.group(1).replace(" ", "")), None, currency

    # "до 200 000"
    to_match = re.search(r"до\s+([\d\s]+)", text)
    if to_match:
        return None, int(to_match.group(1).replace(" ", "")), currency

    # Single number
    num_match = re.search(r"(\d[\d\s]*\d)", text)
    if num_match:
        val = int(num_match.group(1).replace(" ", ""))
        return val, val, currency

    return None, None, currency


def _extract_work_format(card: Tag) -> str:
    """Extract work format from tags and compensation labels."""
    text = card.get_text(" ", strip=True).lower()
    if "можно удалённ" in text or "удалённая работа" in text:
        return "remote"
    if "гибрид" in text:
        return "hybrid"
    if "полный день" in text:
        return "fullDay"
    return ""


def _parse_vacancy_card(card: Tag) -> Vacancy | None:
    try:
        title_el = card.select_one('[data-qa="serp-item__title"]')
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        id_match = re.search(r"/vacancy/(\d+)", href)
        if not id_match:
            return None
        vid = id_match.group(1)

        company_el = card.select_one('[data-qa="vacancy-serp__vacancy-employer-text"]')
        company = company_el.get_text(strip=True) if company_el else ""

        city_el = card.select_one('[data-qa="vacancy-serp__vacancy-address"]')
        city = city_el.get_text(strip=True) if city_el else ""

        # Salary — find leaf span with currency symbol
        salary_from = None
        salary_to = None
        currency = "RUR"
        for span in card.find_all("span"):
            if span.find("span"):
                continue
            txt = span.get_text(strip=True)
            if any(s in txt for s in ("₽", "$", "€")):
                salary_from, salary_to, currency = _parse_salary(txt)
                break

        return Vacancy(
            id=vid,
            title=title,
            company=company,
            city=city,
            salary_from=salary_from,
            salary_to=salary_to,
            currency=currency,
            work_format=_extract_work_format(card),
            description="",
            url=f"https://hh.ru/vacancy/{vid}",
            published_at=datetime.utcnow(),
            source="hh.ru",
        )
    except Exception as e:
        logger.warning(f"Failed to parse vacancy card: {e}")
        return None


class HHFetcher:
    async def fetch_vacancies(self, query: str, prefs: UserPreferences) -> list[Vacancy]:
        area_id = CITY_AREA_MAP.get(prefs.city.lower().strip(), 1)
        params: dict = {
            "text": query,
            "area": area_id,
            "per_page": min(prefs.max_results_per_run, 100),
            "page": 0,
            "order_by": "publication_time",
            "hhtmFrom": "vacancy_search_list",
        }
        if prefs.salary_min and prefs.salary_min > 0:
            params["salary"] = prefs.salary_min
            params["only_with_salary"] = "true"
        schedule = SCHEDULE_MAP.get(prefs.work_format)
        if schedule:
            params["schedule"] = schedule

        vacancies: list[Vacancy] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            try:
                resp = await client.get(HH_SEARCH_URL, params=params, timeout=15.0)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select('[data-qa="vacancy-serp__vacancy"]')
                logger.info(f"HH scrape: '{query}' → {len(cards)} results")

                for card in cards:
                    v = _parse_vacancy_card(card)
                    if v is None:
                        continue
                    if prefs.excluded_companies and any(
                        ex.lower() in v.company.lower() for ex in prefs.excluded_companies if ex
                    ):
                        continue
                    vacancies.append(v)
            except httpx.HTTPStatusError as e:
                logger.error(f"HH scrape error {e.response.status_code}")
            except Exception as e:
                logger.error(f"HH scrape error: {e}")
        return vacancies

    async def get_vacancy_details(self, vacancy_id: str) -> str | None:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            try:
                resp = await client.get(
                    f"{HH_VACANCY_URL}/{vacancy_id}", timeout=15.0
                )
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                desc_el = soup.select_one('[data-qa="vacancy-description"]')
                if desc_el:
                    return desc_el.get_text(" ", strip=True)[:3000]
            except Exception as e:
                logger.warning(f"Details fetch failed {vacancy_id}: {e}")
        return None


hh_fetcher = HHFetcher()
