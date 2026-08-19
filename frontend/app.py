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


def describe_error(exc: Exception) -> str:
    """requests' HTTPError.__str__() is just the generic status line
    ("502 Server Error: Bad Gateway for url: ..."), which throws away the
    `detail` message the backend actually put in the JSON body (see the
    502 handling added in routers/plans.py, routers/actions.py, main.py).
    Prefer that detail when there is one -- it's what actually explains a
    failure (e.g. "Agent AI unreachable: ReadTimeout")."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            detail = response.json().get("detail")
            if detail:
                return detail
        except ValueError:
            pass
    return str(exc)


# Human-readable label per status, for the trace table below -- the raw
# ActionStatus strings (see backend/app/schemas.py) are fine as JSON but
# not great to scan visually in a table.
_STATUS_LABELS = {
    "proposed": "📝 proposed",
    "approved": "👍 approved",
    "refused": "🚫 refused",
    "executed": "✅ executed",
    "error": "❌ error",
    "undone": "↩️ undone",
}


def fetch_audit_trace(plan_id: str) -> list[dict] | None:
    """GET /audit?plan_id=... -- full chronological trace of one plan
    (proposed -> approved -> executed/error/undone), across every action
    and tool, already sorted oldest-first by the backend (see
    routers/audit.py). Returns None (not an empty list) on failure, so
    callers can tell "no entries yet" apart from "couldn't even ask"."""
    try:
        response = requests.get(f"{BACKEND_URL}/audit", params={"plan_id": plan_id}, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        st.warning(f"Impossible de récupérer la trace : {describe_error(exc)}")
        return None


def render_audit_trace(entries: list[dict]) -> None:
    """Reshape raw AuditLogRead rows into a readable table: trim the
    timestamp's microseconds (noise for a human reading a sequence) and
    turn the status into an icon + label."""
    if not entries:
        st.info("Aucune entrée d'audit pour ce plan.")
        return
    rows = [
        {
            "Horodatage": entry["timestamp"][:19].replace("T", " "),
            "Outil": entry["tool"],
            "Statut": _STATUS_LABELS.get(entry["status"], entry["status"]),
            "Note": entry.get("note") or "",
        }
        for entry in entries
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)


st.set_page_config(page_title="Onboarding Agent", page_icon="✅", layout="centered")

# --- Session state -------------------------------------------------------
# Streamlit reruns the whole script top to bottom on every interaction, so
# the generated plan has to be kept in session_state to survive from one
# rerun to the next. The checkbox choices don't need their own dict: each
# st.checkbox(..., key=...) already persists its own value in session_state,
# keyed by the (fresh, per-plan) action id.
if "plan" not in st.session_state:
    st.session_state.plan = None
if "trace" not in st.session_state:
    # Last audit trace fetched for st.session_state.plan (see
    # fetch_audit_trace) -- kept apart from `plan` so a plan can be
    # displayed before its trace has ever been fetched (None) vs. fetched
    # but genuinely empty ([]).
    st.session_state.trace = None

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
            st.session_state.trace = None  # nouveau plan -> l'ancienne trace ne correspond plus
        except Exception as exc:
            st.error(f"Impossible de générer le plan : {describe_error(exc)}")
            st.session_state.plan = None

# --- 2. Plan proposé (checklist) -------------------------------------------

plan = st.session_state.plan

if plan:
    if not plan["actions"]:
        # Peut arriver plus souvent que prévu avec un petit modèle local
        # (voir les limites documentées côté agent/mcp-server) -- sans ce
        # cas, l'écran affichait "Plan proposé (0 actions)" avec une
        # checklist vide et un bouton désactivé, sans explication.
        st.warning(
            "Aucune action pertinente n'a été identifiée pour cette demande. "
            "Essayez de reformuler avec une intention liée à l'onboarding d'un collaborateur."
        )
    else:
        st.subheader(f"Plan proposé ({len(plan['actions'])} actions)")

        # Each checkbox is pre-checked, matching the original wireframe. The
        # key is scoped to this plan's action id, so a freshly generated
        # plan (new ids) always starts fully checked -- Streamlit only
        # respects `value=` the first time it sees a given key.
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
                    # Step 1: send the human's approve/refuse decision for
                    # every proposed action.
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
                    st.session_state.trace = fetch_audit_trace(plan["id"])
                except Exception as exc:
                    st.error(f"Échec de l'exécution : {describe_error(exc)}")

        # Persiste en dehors du bloc "Exécuter" ci-dessus (pas juste au
        # moment du clic) pour rester affichée sur les reruns suivants --
        # ex. quand tu coches/décoches une action après une première
        # exécution.
        if st.session_state.trace is not None:
            st.subheader("Traçabilité de ce plan")
            st.caption(f"Plan `{plan['id']}` — du plus ancien au plus récent (GET /audit?plan_id=...).")
            render_audit_trace(st.session_state.trace)
            if st.button("Rafraîchir la trace"):
                st.session_state.trace = fetch_audit_trace(plan["id"])
                st.rerun()

# --- Traçabilité : retrouver un plan précédent ----------------------------
# Utile si la page a été rechargée (session_state.plan reparti à None) mais
# que tu as garde un id de plan -- ex. depuis un log, ou une exécution
# precedente -- sans redemander un nouveau plan au LLM pour autant.

with st.expander("Retrouver la trace d'un plan précédent"):
    st.caption("Colle l'id d'un plan déjà généré pour revoir sa séquence d'appels complète.")
    lookup_plan_id = st.text_input("Plan ID", key="lookup_plan_id", label_visibility="collapsed")
    if st.button("Afficher la trace", disabled=not lookup_plan_id.strip()):
        entries = fetch_audit_trace(lookup_plan_id.strip())
        if entries is not None:
            render_audit_trace(entries)

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
            st.error(f"Backend injoignable : {describe_error(exc)}")

    if st.button("Vérifier l'agent (rapide, sans LLM)"):
        # This is the palier 2 gate: backend <-> agent reachability, no
        # Ollama call, no meaningful memory footprint.
        try:
            response = requests.get(f"{BACKEND_URL}/agent/ping", timeout=15)
            response.raise_for_status()
            st.success(f"Agent joignable : {response.json()}")
        except Exception as exc:
            st.error(f"Agent injoignable : {describe_error(exc)}")

    if st.button("Vérifier l'agent + LLM (optionnel)"):
        st.caption("Peut échouer si la machine n'a pas assez de RAM pour charger le modèle — indépendant du code.")
        with st.spinner("Appel de l'agent (peut prendre du temps sur un premier chargement du modèle)…"):
            try:
                # Must stay above agent_client.py's _PING_LLM_TIMEOUT (90s)
                # on the backend side, or this button times out before the
                # backend itself gives up.
                response = requests.get(f"{BACKEND_URL}/agent/ping-llm", timeout=130)
                response.raise_for_status()
                st.success(f"Agent + LLM joignables : {response.json()}")
            except Exception as exc:
                st.error(f"Agent + LLM : {describe_error(exc)}")
