"""
Minimal version, just to check that the container starts and that the
docker-compose network works correctly between frontend and backend.
No prompt, no checklist, no audit log yet — that comes once the backend
has real endpoints to call (see the backend's step-by-step build).
"""

import os

import requests
import streamlit as st

st.set_page_config(page_title="Agent d'onboarding")
st.title("Agent d'onboarding — Frontend")
st.write("Le frontend démarre correctement.")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

if st.button("Vérifier la connexion au backend"):
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        response.raise_for_status()
        st.success(f"Backend joignable ({BACKEND_URL}) : {response.json()}")
    except Exception as exc:
        st.error(f"Backend injoignable sur {BACKEND_URL}/health : {exc}")
