"""Sidebar — навигация и статус"""

from datetime import timedelta

import httpx
import streamlit as st

from streamlit_app.config import API


def _get_stats():
    try:
        r = httpx.get(f"{API}/stats", timeout=5)
        if r.status_code == 200:
            return r.json()
        return None
    except httpx.ConnectError:
        return None
    except httpx.TimeoutException:
        return None
    except Exception:
        return None


@st.fragment(run_every=timedelta(seconds=10))
def _live_stats():
    stats = _get_stats()
    count = stats.get("vacancies_in_db", 0) if stats else 0
    has_resume = stats.get("has_resume") if stats else False
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Вакансий в БД", count)
    with col2:
        st.metric("Резюме", "✅" if has_resume else "❌")


def render():
    st.markdown("## 🎯 Job Analyzer")
    st.markdown("---")

    stats = _get_stats()

    if stats:
        st.markdown(
            '<span style="color:#4ade80;font-size:13px;">● API подключён</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span style="color:#6b7280;font-size:13px;">● API недоступен</span>',
            unsafe_allow_html=True,
        )
        st.caption("Проверьте: docker compose up")

    _live_stats()

    st.markdown("---")
    st.markdown("**Навигация**")

    pages = [
        ("resume", "📄 Резюме"),
        ("preferences", "⚙️  Предпочтения"),
        ("analyze", "🔍 Анализ"),
        ("results", "📊 Результаты"),
    ]

    for key, label in pages:
        if st.button(label, key=f"nav_{key}", use_container_width=True):
            st.session_state["page"] = key
            st.rerun()

    st.markdown("---")
    st.caption("MVP v1.0 · GigaChat + hh.ru API")
