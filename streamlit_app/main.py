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

.stApp { background: #0f1117; }

.metric-card {
    background: #1a1d27;
    border: 1px solid #2d3148;
    border-radius: 12px;
    padding: 20px 24px;
    text-align: center;
}
.metric-card .val {
    font-size: 36px;
    font-weight: 700;
    color: #818cf8;
    font-family: 'Space Grotesk', sans-serif;
}
.metric-card .label {
    font-size: 13px;
    color: #6b7280;
    margin-top: 4px;
}

.vacancy-card {
    background: #1a1d27;
    border: 1px solid #2d3148;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 12px;
    transition: border-color 0.2s;
}
.vacancy-card:hover { border-color: #818cf8; }

.score-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
}
.score-high { background: #14532d; color: #4ade80; }
.score-mid  { background: #451a03; color: #fb923c; }
.score-low  { background: #450a0a; color: #f87171; }

.tag {
    display: inline-block;
    background: #1e2235;
    border: 1px solid #3d4266;
    border-radius: 6px;
    padding: 2px 10px;
    font-size: 12px;
    color: #a5b4fc;
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
