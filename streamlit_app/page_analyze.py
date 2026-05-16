"""Страница запуска анализа"""

import os
import time

import httpx
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")


def _check_status() -> dict:
    try:
        return httpx.get(f"{API}/analysis/status", timeout=3).json()
    except Exception:
        return {"running": False}


def _check_ready() -> tuple[bool, str]:
    try:
        stats = httpx.get(f"{API}/stats", timeout=3).json()
        if not stats.get("has_resume"):
            return False, "❌ Резюме не загружено — перейдите на страницу **Резюме**"
        return True, "✅ Всё готово к анализу"
    except Exception:
        return False, "❌ API недоступен"


def render():
    st.title("🔍 Запуск анализа")
    st.markdown("Парсинг hh.ru → ChromaDB embeddings → GigaChat LLM-ранжирование.")

    ready, msg = _check_ready()
    st.success(msg) if ready else st.warning(msg)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        top_n = st.slider("Топ N вакансий в результате", 5, 20, 10)
    with col2:
        st.info("💡 Анализ занимает 2–5 минут")

    st.markdown(
        "**Пайплайн:** `hh.ru API` → `ChromaDB` → `Semantic Search` → `GigaChat LLM` → `Результаты`"
    )
    st.markdown("---")

    is_running = _check_status().get("running", False)

    if is_running:
        with st.spinner("Идёт анализ... Обычно 2-5 минут"):
            while True:
                time.sleep(4)
                if not _check_status().get("running"):
                    break
        st.success("✅ Готово!")
        st.session_state["page"] = "results"
        st.rerun()
    else:
        col_a, col_b, _ = st.columns([1, 1, 2])
        with col_a:
            if st.button(
                "🚀 Запустить анализ", type="primary", disabled=not ready, use_container_width=True
            ):
                try:
                    r = httpx.post(f"{API}/analysis/run", params={"top_n": top_n}, timeout=10)
                    if r.status_code == 200:
                        st.success("Запущен!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(r.json().get("detail", r.text))
                except Exception as e:
                    st.error(f"API недоступен: {e}")
        with col_b:
            if st.button("🗑️ Очистить БД", use_container_width=True):
                try:
                    httpx.delete(f"{API}/data/clear", timeout=5)
                    st.success("БД очищена")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")
