"""
Streamlit UI — главный файл приложения.
"""

import streamlit as st

st.set_page_config(
    page_title="Job Analyzer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Инжектируем стили
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; }

.stApp { background: #f5f7fa; }

.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px 24px;
    text-align: center;
}
.metric-card .val {
    font-size: 36px;
    font-weight: 700;
    color: #4f46e5;
    font-family: 'Space Grotesk', sans-serif;
}
.metric-card .label {
    font-size: 13px;
    color: #64748b;
    margin-top: 4px;
}

.vacancy-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 12px;
    transition: border-color 0.2s;
}
.vacancy-card:hover { border-color: #4f46e5; }

.score-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
}
.score-high { background: #dcfce7; color: #15803d; }
.score-mid  { background: #fef3c7; color: #b45309; }
.score-low  { background: #fee2e2; color: #dc2626; }

.tag {
    display: inline-block;
    background: #eef2ff;
    border: 1px solid #c7d2fe;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 12px;
    color: #4f46e5;
    margin: 2px;
}

.status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
}
.dot-green { background: #4ade80; }
.dot-gray  { background: #6b7280; }
</style>
""",
    unsafe_allow_html=True,
)

from streamlit_app import (  # noqa: E402
    page_analyze,
    page_preferences,
    page_results,
    page_resume,
    sidebar,
)

# Навигация
with st.sidebar:
    sidebar.render()

page = st.session_state.get("page", "resume")

if page == "resume":
    page_resume.render()
elif page == "preferences":
    page_preferences.render()
elif page == "analyze":
    page_analyze.render()
elif page == "results":
    page_results.render()
