"""
Version minimale, juste pour vérifier que le container démarre et que le
réseau docker-compose fonctionne bien entre frontend et backend.
Pas de prompt, pas de checklist, pas de journal — ça arrive une fois que le
backend a de vrais endpoints à appeler (cf. l'étape par étape côté backend).
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
