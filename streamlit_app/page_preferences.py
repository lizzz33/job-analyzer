"""Страница настройки предпочтений"""

import httpx
import streamlit as st

from streamlit_app.config import API

CITIES = [
    "Москва",
    "Санкт-Петербург",
    "Екатеринбург",
    "Новосибирск",
    "Казань",
    "Нижний Новгород",
    "Самара",
    "Краснодар",
    "Уфа",
    "Удалённо",
]

WORK_FORMATS = {"any": "Любой", "remote": "Удалённо", "office": "Офис", "hybrid": "Гибрид"}


def _load_prefs() -> dict:
    try:
        r = httpx.get(f"{API}/preferences", timeout=5)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def render():
    st.title("⚙️ Предпочтения")
    st.markdown("Настройте параметры поиска — они учитываются при ранжировании вакансий.")

    prefs = st.session_state.get("prefs") or _load_prefs()

    with st.form("prefs_form"):
        col1, col2 = st.columns(2)
        with col1:
            city_val = prefs.get("city", "Москва")
            opts = CITIES if city_val in CITIES else [city_val] + CITIES
            city = st.selectbox(
                "Город", opts, index=opts.index(city_val) if city_val in opts else 0
            )
        with col2:
            fmt_val = prefs.get("work_format", "any")
            fmt = st.selectbox(
                "Формат работы",
                list(WORK_FORMATS.keys()),
                format_func=lambda x: WORK_FORMATS[x],
                index=list(WORK_FORMATS.keys()).index(fmt_val) if fmt_val in WORK_FORMATS else 0,
            )

        col3, col4 = st.columns(2)
        with col3:
            salary_min = st.slider(
                "Минимальная зарплата (руб.)",
                min_value=0,
                max_value=1_000_000,
                value=prefs.get("salary_min") or 0,
                step=10_000,
            )
        with col4:
            include_no_salary = st.checkbox(
                "Включать вакансии без указанной ЗП",
                value=prefs.get("include_no_salary", False),
            )
        max_results = st.slider(
            "Вакансий за запрос", 10, 100, value=prefs.get("max_results_per_run", 50), step=10
        )

        keywords_str = st.text_input(
            "Ключевые слова для поиска",
            value=", ".join(prefs.get("keywords", [])),
            placeholder="python developer, data engineer, ML engineer",
            help="Через запятую. Используются как запросы на hh.ru",
        )

        col5, col6 = st.columns(2)
        with col5:
            preferred_str = st.text_area(
                "Приоритетные компании",
                value="\n".join(prefs.get("preferred_companies", [])),
                placeholder="Яндекс\nСбер",
                height=100,
            )
        with col6:
            excluded_str = st.text_area(
                "Стоп-лист компаний",
                value="\n".join(prefs.get("excluded_companies", [])),
                placeholder="Компания которую не хочу",
                height=100,
            )

        extra = st.text_area(
            "Дополнительные пожелания",
            value=prefs.get("extra_interests", ""),
            placeholder="Интересуют стартапы, fintech, AI. Не рассматриваю аутсорс.",
            height=100,
        )

        if st.form_submit_button("💾 Сохранить", type="primary", use_container_width=True):
            payload = {
                "city": city,
                "work_format": fmt,
                "salary_min": salary_min if salary_min > 0 else None,
                "include_no_salary": include_no_salary,
                "max_results_per_run": max_results,
                "keywords": [k.strip() for k in keywords_str.split(",") if k.strip()],
                "preferred_companies": [c.strip() for c in preferred_str.splitlines() if c.strip()],
                "excluded_companies": [c.strip() for c in excluded_str.splitlines() if c.strip()],
                "extra_interests": extra,
            }
            try:
                r = httpx.post(f"{API}/preferences", json=payload, timeout=10)
                if r.status_code == 200:
                    st.success("✅ Предпочтения сохранены!")
                    st.session_state["prefs"] = payload
                else:
                    st.error(f"Ошибка: {r.text}")
            except Exception as e:
                st.error(f"API недоступен: {e}")
