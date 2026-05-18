"""Страница запуска анализа"""

from datetime import timedelta

import httpx
import streamlit as st

from streamlit_app.config import API


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


@st.fragment(run_every=timedelta(seconds=5))
def _poll_completion():
    """Auto-refresh fragment — polls backend and redirects when analysis finishes."""
    status = _check_status()
    if not status.get("running", False):
        if "analysis_started" in st.session_state:
            del st.session_state["analysis_started"]
        st.session_state["page"] = "results"
        st.rerun()


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
        st.info("💡 Анализ занимает 1–2 минуты")

    st.markdown(
        "**Пайплайн:** `hh.ru API` → `ChromaDB` → `Semantic Search` → `GigaChat LLM` → `Результаты`"
    )
    st.markdown("---")

    is_running = _check_status().get("running", False)

    if is_running:
        st.info("⏳ Идёт анализ... Обычно 1-2 минуты. Страница обновляется автоматически.")
        _poll_completion()
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
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")

    # Auto-redirect to results if analysis just finished
    if "analysis_started" in st.session_state and not is_running:
        del st.session_state["analysis_started"]
        st.session_state["page"] = "results"
        st.rerun()

    if is_running and "analysis_started" not in st.session_state:
        st.session_state["analysis_started"] = True
