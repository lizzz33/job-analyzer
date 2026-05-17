"""Shared config for Streamlit app — reads from the same settings as the API."""

import os

API = os.getenv("API_BASE_URL", "http://localhost:8000")
