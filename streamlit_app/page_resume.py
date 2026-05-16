"""Страница загрузки и просмотра резюме"""

import os

import httpx
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")


def render():
    st.title("📄 Загрузка резюме")
    st.markdown("Загрузите резюме — GigaChat извлечёт навыки и профиль автоматически.")

    uploaded = st.file_uploader("PDF, DOCX или TXT", type=["pdf", "docx", "txt"])

    if uploaded and st.button("🚀 Загрузить и распарсить", type="primary"):
        with st.spinner("Анализирую резюме через GigaChat..."):
            try:
                resp = httpx.post(
                    f"{API}/resume/upload",
                    files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                    timeout=60,
                )
                if resp.status_code == 200:
                    st.success("✅ Резюме загружено и проанализировано!")
                    st.session_state["profile"] = resp.json().get("profile", {})
                    st.rerun()
                else:
                    st.error(f"Ошибка: {resp.json().get('detail', resp.text)}")
            except Exception as e:
                st.error(f"Не удалось подключиться к API: {e}")

    st.markdown("---")
    st.markdown("### Текущий профиль")

    profile = st.session_state.get("profile")
    if not profile:
        try:
            r = httpx.get(f"{API}/resume/profile", timeout=5)
            if r.status_code == 200:
                profile = r.json()
                st.session_state["profile"] = profile
        except Exception:
            pass

    if profile:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown(f"**{profile.get('name') or '—'}**")
            st.markdown(f"*{profile.get('position') or 'Должность не определена'}*")
            st.markdown(
                f"🏙️ {profile.get('city') or '—'}  &nbsp; 💼 {profile.get('experience_years') or '?'}"
            )
            if profile.get("education"):
                st.markdown(f"🎓 {profile['education']}")
        with col2:
            skills = profile.get("skills", [])
            if skills:
                st.markdown("**Навыки:**")
                tags = "  ".join(f"`{s}`" for s in skills[:20])
                st.markdown(tags)
        if profile.get("summary"):
            st.info(profile["summary"])
    else:
        st.info("Резюме не загружено.")
        with st.expander("💡 Советы"):
            st.markdown("""
- PDF даёт лучший результат
- Укажите чёткие навыки и должность
- Поддерживаются русский и английский
            """)
