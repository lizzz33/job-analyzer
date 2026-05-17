"""Tests for HH fetcher — salary parsing, vacancy parsing, async fetching."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import UserPreferences, WorkFormat

# ── _parse_salary ──────────────────────────────────────────────────────────────


class TestParseSalary:
    def test_from_salary(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("от 200 000 ₽")
        assert sal_from == 200000
        assert sal_to is None
        assert cur == "RUR"

    def test_to_salary(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("до 4 000 $")
        assert sal_from is None
        assert sal_to == 4000
        assert cur == "USD"

    def test_range_salary(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("100 000 — 200 000 ₽")
        assert sal_from == 100000
        assert sal_to == 200000
        assert cur == "RUR"

    def test_euro_salary(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("от 5 000 €")
        assert sal_from == 5000
        assert cur == "EUR"

    def test_single_number(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("150 000 руб")
        assert sal_from == 150000
        assert sal_to == 150000
        assert cur == "RUR"

    def test_no_salary(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("без указания")
        assert sal_from is None
        assert sal_to is None
        assert cur == "RUR"

    def test_nbsp_handling(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("от 300 000 ₽")
        assert sal_from == 300000

    def test_minus_as_dash(self):
        from app.services.hh_fetcher import _parse_salary

        sal_from, sal_to, cur = _parse_salary("100 000 − 200 000 ₽")
        assert sal_from == 100000
        assert sal_to == 200000


# ── CITY_AREA_MAP ──────────────────────────────────────────────────────────────


class TestCityAreaMap:
    def test_known_cities(self):
        from app.services.hh_fetcher import CITY_AREA_MAP

        assert CITY_AREA_MAP["москва"] == 1
        assert CITY_AREA_MAP["спб"] == 2
        assert CITY_AREA_MAP["казань"] == 88

    def test_remote_city(self):
        from app.services.hh_fetcher import CITY_AREA_MAP

        assert CITY_AREA_MAP["удаленно"] == 113
        assert CITY_AREA_MAP["remote"] == 113


# ── SCHEDULE_MAP ───────────────────────────────────────────────────────────────


class TestScheduleMap:
    def test_work_format_mapping(self):
        from app.services.hh_fetcher import SCHEDULE_MAP

        assert SCHEDULE_MAP[WorkFormat.remote] == "remote"
        assert SCHEDULE_MAP[WorkFormat.office] == "fullDay"
        assert SCHEDULE_MAP[WorkFormat.hybrid] == "flexible"
        assert SCHEDULE_MAP[WorkFormat.any] is None


# ── _parse_vacancy_card ────────────────────────────────────────────────────────


class TestParseVacancyCard:
    def _make_card(self, **kwargs):
        from bs4 import BeautifulSoup

        title = kwargs.get("title", "Dev")
        vid = kwargs.get("vid", "42")
        company = kwargs.get("company", "Co")
        city = kwargs.get("city", "Москва")
        salary = kwargs.get("salary", "от 150 000 ₽")
        work_format_text = kwargs.get("work_format_text", "")

        wf_tag = ""
        if work_format_text:
            wf_tag = f'<span data-qa="work-format">{work_format_text}</span>'

        html = f"""
        <div data-qa="vacancy-serp__vacancy">
          <a data-qa="serp-item__title" href="https://hh.ru/vacancy/{vid}">{title}</a>
          <span data-qa="vacancy-serp__vacancy-employer-text">{company}</span>
          <span data-qa="vacancy-serp__vacancy-address">{city}</span>
          <span>{salary}</span>
          {wf_tag}
          <span data-qa="vacancy-serp__vacancy-date">15 мая 2025</span>
        </div>
        """
        soup = BeautifulSoup(html, "lxml")
        return soup.select_one('[data-qa="vacancy-serp__vacancy"]')

    def test_full_card(self):
        from app.services.hh_fetcher import _parse_vacancy_card

        card = self._make_card(title="Backend Dev", vid="777", company="Yandex", salary="200 000 — 350 000 ₽")
        v = _parse_vacancy_card(card)

        assert v is not None
        assert v.id == "777"
        assert v.title == "Backend Dev"
        assert v.company == "Yandex"
        assert v.salary_from == 200000
        assert v.salary_to == 350000
        assert v.currency == "RUR"
        assert v.url == "https://hh.ru/vacancy/777"
        assert v.source == "hh.ru"

    def test_card_no_title_link_returns_none(self):
        from bs4 import BeautifulSoup

        from app.services.hh_fetcher import _parse_vacancy_card

        html = '<div data-qa="vacancy-serp__vacancy"><span>No title</span></div>'
        soup = BeautifulSoup(html, "lxml")
        card = soup.select_one('[data-qa="vacancy-serp__vacancy"]')

        assert _parse_vacancy_card(card) is None

    def test_card_no_vacancy_id_in_url(self):
        from bs4 import BeautifulSoup

        from app.services.hh_fetcher import _parse_vacancy_card

        html = """
        <div data-qa="vacancy-serp__vacancy">
          <a data-qa="serp-item__title" href="https://hh.ru/other/page">Title</a>
        </div>
        """
        soup = BeautifulSoup(html, "lxml")
        card = soup.select_one('[data-qa="vacancy-serp__vacancy"]')

        assert _parse_vacancy_card(card) is None


# ── HHFetcher async ────────────────────────────────────────────────────────────


def _mock_search_html(vacancies=None):
    """Build HTML with vacancy cards for the search page."""
    if vacancies is None:
        vacancies = [
            {"id": "100", "title": "Dev", "company": "Co", "salary": "от 100 000 ₽"},
        ]

    cards_html = ""
    for v in vacancies:
        cards_html += f"""
        <div data-qa="vacancy-serp__vacancy">
          <a data-qa="serp-item__title" href="https://hh.ru/vacancy/{v['id']}">{v['title']}</a>
          <span data-qa="vacancy-serp__vacancy-employer-text">{v.get('company', '')}</span>
          <span data-qa="vacancy-serp__vacancy-address">Москва</span>
          <span>{v.get('salary', '')}</span>
        </div>
        """

    return f"<html><body>{cards_html}</body></html>"


class TestHHFetcher:
    @pytest.mark.asyncio
    async def test_fetch_vacancies_returns_list(self):
        from app.services.hh_fetcher import HHFetcher

        fetcher = HHFetcher()
        html = _mock_search_html()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        prefs = UserPreferences(city="Москва", max_results_per_run=50)

        with patch("httpx.AsyncClient") as mock_client:
            cm = AsyncMock()
            cm.get.return_value = mock_resp
            cm.__aenter__ = AsyncMock(return_value=cm)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm

            results = await fetcher.fetch_vacancies("Python", prefs)

        assert len(results) >= 1
        assert results[0].id == "100"

    @pytest.mark.asyncio
    async def test_fetch_vacancies_stops_on_404(self):
        from app.services.hh_fetcher import HHFetcher

        fetcher = HHFetcher()
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        prefs = UserPreferences(city="Москва")

        with patch("httpx.AsyncClient") as mock_client:
            cm = AsyncMock()
            cm.get.return_value = mock_resp
            cm.__aenter__ = AsyncMock(return_value=cm)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm

            results = await fetcher.fetch_vacancies("Python", prefs)

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_vacancies_excludes_companies(self):
        from app.services.hh_fetcher import HHFetcher

        fetcher = HHFetcher()
        html = _mock_search_html([
            {"id": "1", "title": "Dev", "company": "BadCorp"},
            {"id": "2", "title": "Dev2", "company": "GoodCorp", "salary": "100 000 ₽"},
        ])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        prefs = UserPreferences(
            city="Москва", excluded_companies=["BadCorp"], max_results_per_run=50
        )

        with patch("httpx.AsyncClient") as mock_client:
            cm = AsyncMock()
            cm.get.return_value = mock_resp
            cm.__aenter__ = AsyncMock(return_value=cm)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm

            results = await fetcher.fetch_vacancies("Python", prefs)

        ids = [v.id for v in results]
        assert "1" not in ids
        assert "2" in ids

    @pytest.mark.asyncio
    async def test_get_vacancy_details_success(self):
        from app.services.hh_fetcher import HHFetcher

        fetcher = HHFetcher()
        html = '<html><div data-qa="vacancy-description">Detailed description here</div></html>'

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            cm = AsyncMock()
            cm.get.return_value = mock_resp
            cm.__aenter__ = AsyncMock(return_value=cm)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm

            result = await fetcher.get_vacancy_details("12345")

        assert result == "Detailed description here"

    @pytest.mark.asyncio
    async def test_get_vacancy_details_failure_returns_none(self):
        from app.services.hh_fetcher import HHFetcher

        fetcher = HHFetcher()

        with patch("httpx.AsyncClient") as mock_client:
            cm = AsyncMock()
            cm.get.side_effect = Exception("Network error")
            cm.__aenter__ = AsyncMock(return_value=cm)
            cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = cm

            result = await fetcher.get_vacancy_details("12345")

        assert result is None
