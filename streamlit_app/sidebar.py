"""Sidebar — навигация и статус"""

import os

import httpx
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")


def _get_stats():
    try:
        r = httpx.get(f"{API}/stats", timeout=3)
        return r.json()
    except Exception:
        return None


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

    if stats:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Вакансий в БД", stats.get("vacancies_in_db", 0))
        with col2:
            st.metric("Резюме", "✅" if stats.get("has_resume") else "❌")

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
