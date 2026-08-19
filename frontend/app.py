"""
Onboarding Agent -- frontend (Streamlit).

Adapted from a first HTML/CSS/JS draft (vanilla, same-origin fetch calls)
into Streamlit, to match this project's actual stack: a separate backend
service reached via BACKEND_URL, not a same-origin static page served by
FastAPI. The frontend only ever talks to the backend -- never directly to
the Agent AI or the MCP server, matching the tool-boundary rules in
ARCHITECTURE.md.

Flow (unchanged from the original draft): generate a plan (POST /plans),
let the human check/uncheck each proposed action, then submit the
decisions (PATCH /actions/{id}) and execute the approved ones
(POST /plans/{id}/execute).
"""

import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")

st.set_page_config(page_title="Onboarding Agent", page_icon="✅", layout="centered")

# --- Session state -------------------------------------------------------
# Streamlit reruns the whole script top to bottom on every interaction, so
# the generated plan has to be kept in session_state to survive from one
# rerun to the next. The checkbox choices don't need their own dict: each
# st.checkbox(..., key=...) already persists its own value in session_state,
# keyed by the (fresh, per-plan) action id.
if "plan" not in st.session_state:
    st.session_state.plan = None

st.title("Holberton — :blue[Onboarding Agent]")

# --- 1. Prompt -------------------------------------------------------------

st.subheader("Décrivez l'arrivée du collaborateur")

prompt = st.text_area(
    "Intention en langage naturel",
    placeholder="On accueille Camille, nouvelle développeuse, elle arrive le 3 mars dans l'équipe Backend.",
    label_visibility="collapsed",
)

if st.button("Générer le plan", type="primary", disabled=not prompt.strip()):
    with st.spinner("Génération du plan…"):
        try:
            response = requests.post(f"{BACKEND_URL}/plans", json={"prompt": prompt}, timeout=60)
            response.raise_for_status()
            st.session_state.plan = response.json()
        except Exception as exc:
            st.error(f"Impossible de générer le plan : {exc}")
            st.session_state.plan = None

# --- 2. Plan proposé (checklist) -------------------------------------------

plan = st.session_state.plan

if plan:
    st.subheader(f"Plan proposé ({len(plan['actions'])} actions)")

    # Each checkbox is pre-checked, matching the original wireframe. The key
    # is scoped to this plan's action id, so a freshly generated plan (new
    # ids) always starts fully checked -- Streamlit only respects `value=`
    # the first time it sees a given key.
    checkbox_states = {
        action["id"]: st.checkbox(action["summary"], value=True, key=f"action_{action['id']}")
        for action in plan["actions"]
    }

    selected_count = sum(checkbox_states.values())
    total_count = len(plan["actions"])
    st.caption(f"{selected_count} action(s) sélectionnée(s) sur {total_count}")

    if st.button("Exécuter la sélection", type="primary", disabled=selected_count == 0):
        with st.spinner("Exécution…"):
            try:
                # Step 1: send the human's approve/refuse decision for every
                # proposed action.
                for action in plan["actions"]:
                    decision_status = "approved" if checkbox_states[action["id"]] else "refused"
                    decision = requests.patch(
                        f"{BACKEND_URL}/actions/{action['id']}",
                        json={"status": decision_status},
                        timeout=30,
                    )
                    decision.raise_for_status()

                # Step 2: trigger execution of the now-approved actions.
                execution = requests.post(f"{BACKEND_URL}/plans/{plan['id']}/execute", timeout=60)
                execution.raise_for_status()
                results = execution.json()

                executed_count = sum(1 for r in results if r["status"] == "executed")
                st.success(f"{executed_count} action(s) exécutée(s) sur {len(results)}.")
                st.caption("Suivi d'exécution détaillé et journal d'audit : à venir dans une prochaine itération.")
            except Exception as exc:
                st.error(f"Échec de l'exécution : {exc}")

# --- Diagnostic (palier 2) --------------------------------------------
# Separate from the flow above on purpose: proves the chain frontend ->
# backend -> agent (-> Ollama) actually talks to itself, without depending
# on any project-specific planning/execution logic that isn't built yet.

with st.expander("Diagnostic de connectivité"):
    st.caption("Vérifie que chaque service de la chaîne est bien joignable, indépendamment du flux ci-dessus.")

    if st.button("Vérifier le backend"):
        try:
            response = requests.get(f"{BACKEND_URL}/health", timeout=5)
            response.raise_for_status()
            st.success(f"Backend joignable : {response.json()}")
        except Exception as exc:
            st.error(f"Backend injoignable : {exc}")

    if st.button("Vérifier l'agent (bout en bout)"):
        with st.spinner("Appel de l'agent (peut prendre du temps, le LLM doit répondre)…"):
            try:
                response = requests.get(f"{BACKEND_URL}/agent/ping", timeout=65)
                response.raise_for_status()
                st.success(f"Agent joignable : {response.json()}")
            except Exception as exc:
                st.error(f"Agent injoignable : {exc}")
