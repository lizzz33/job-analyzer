"""Shared config for Streamlit app."""

import os

API = os.getenv("API_BASE_URL", "http://localhost:8000")
