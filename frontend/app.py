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
if "plan" not in st.session_state:
    st.session_state.plan = None
if "trace" not in st.session_state:
    st.session_state.trace = None

# --- Persistance via l'URL --------------------------------------------
# st.session_state est vidé à chaque VRAI rechargement de page (F5, nouvel
# onglet) -- Streamlit recrée une session neuve, pas seulement un rerun.
# On stocke donc l'id du plan courant dans l'URL (st.query_params), qui
# lui survit à un rechargement complet. Au chargement, si un plan_id est
# présent dans l'URL mais qu'on n'a pas encore le plan en session_state,
# on va le rechercher côté backend (GET /plans/{id}, déjà existant) plutôt
# que de forcer l'utilisateur à le recoller à la main.
if st.session_state.plan is None:
    url_plan_id = st.query_params.get("plan_id")
    if url_plan_id:
        try:
            response = requests.get(f"{BACKEND_URL}/plans/{url_plan_id}", timeout=15)
            response.raise_for_status()
            st.session_state.plan = response.json()
            st.session_state.trace = fetch_audit_trace(url_plan_id)
        except Exception as exc:
            st.warning(f"Impossible de recharger le plan depuis l'URL : {describe_error(exc)}")

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
            st.session_state.trace = None
            # Fixe l'id du plan dans l'URL -- survit à un rechargement,
            # contrairement à session_state seul.
            st.query_params["plan_id"] = st.session_state.plan["id"]
        except Exception as exc:
            st.error(f"Impossible de générer le plan : {describe_error(exc)}")
            st.session_state.plan = None

# --- 2. Plan proposé (checklist) -------------------------------------------

plan = st.session_state.plan

if plan:
    if not plan["actions"] and not plan.get("excluded_actions"):
        if plan.get("clarification"):
            st.warning(f"💡 {plan['clarification']}")
        else:
            st.warning(
                "Aucune action pertinente n'a été identifiée pour cette demande. "
                "Essayez de reformuler avec une intention liée à l'onboarding d'un collaborateur."
            )
    else:
        if plan["actions"]:
            st.subheader(f"Plan proposé ({len(plan['actions'])} actions)")

            checkbox_states = {
                action["id"]: st.checkbox(action["summary"], value=True, key=f"action_{action['id']}")
                for action in plan["actions"]
            }

            selected_count = sum(checkbox_states.values())
            total_count = len(plan["actions"])
            st.caption(f"{selected_count} action(s) sélectionnée(s) sur {total_count}")
        else:
            checkbox_states = {}
            selected_count = 0
            st.info("Aucune action autorisée n'a été identifiée pour cette demande.")

        if plan.get("excluded_actions"):
            st.markdown("**🚫 Actions exclues (non autorisées)**")
            for excluded in plan["excluded_actions"]:
                st.markdown(f"~~{excluded['summary']}~~")
                st.caption(f"⚠️ {excluded.get('note', 'Action non autorisée.')}")

        if st.button("Exécuter la sélection", type="primary", disabled=selected_count == 0):
            with st.spinner("Exécution…"):
                try:
                    for action in plan["actions"]:
                        decision_status = "approved" if checkbox_states[action["id"]] else "refused"
                        decision = requests.patch(
                            f"{BACKEND_URL}/actions/{action['id']}",
                            json={"status": decision_status},
                            timeout=30,
                        )
                        decision.raise_for_status()

                    execution = requests.post(f"{BACKEND_URL}/plans/{plan['id']}/execute", timeout=60)
                    execution.raise_for_status()
                    results = execution.json()

                    executed_count = sum(1 for r in results if r["status"] == "executed")
                    st.success(f"{executed_count} action(s) exécutée(s) sur {len(results)}.")
                    st.session_state.trace = fetch_audit_trace(plan["id"])
                except Exception as exc:
                    st.error(f"Échec de l'exécution : {describe_error(exc)}")

        if st.session_state.trace is not None:
            st.subheader("Traçabilité de ce plan")
            st.caption(f"Plan `{plan['id']}` — du plus ancien au plus récent (GET /audit?plan_id=...).")
            render_audit_trace(st.session_state.trace)
            if st.button("Rafraîchir la trace"):
                st.session_state.trace = fetch_audit_trace(plan["id"])
                st.rerun()

# --- Traçabilité : retrouver un plan précédent ----------------------------

with st.expander("Retrouver la trace d'un plan précédent"):
    st.caption("Colle l'id d'un plan déjà généré pour revoir sa séquence d'appels complète.")
    lookup_plan_id = st.text_input("Plan ID", key="lookup_plan_id", label_visibility="collapsed")
    if st.button("Afficher la trace", disabled=not lookup_plan_id.strip()):
        entries = fetch_audit_trace(lookup_plan_id.strip())
        if entries is not None:
            render_audit_trace(entries)
            st.query_params["plan_id"] = lookup_plan_id.strip()

# --- Outils autorisés (lecture seule) --------------------------------

with st.expander("🔧 Outils autorisés"):
    st.caption(
        "Liste des outils que l'agent LLM peut réellement appeler, "
        "définie par la variable ALLOWED_TOOLS du serveur MCP."
    )
    try:
        response = requests.get(f"{BACKEND_URL}/agent/tools", timeout=15)
        response.raise_for_status()
        permissions = response.json()

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**✅ Autorisés**")
            if permissions.get("allowed"):
                for name in permissions["allowed"]:
                    st.write(f"- `{name}`")
            else:
                st.caption("Aucun.")
        with col2:
            st.markdown("**🚫 Non autorisés**")
            if permissions.get("registered_but_not_allowed"):
                for name in permissions["registered_but_not_allowed"]:
                    st.write(f"- `{name}`")
            else:
                st.caption("Aucun.")

        if permissions.get("allowed_but_not_registered"):
            st.warning(
                "⚠️ Dans ALLOWED_TOOLS mais introuvables parmi les tools "
                "réellement définis (faute de frappe ?) : "
                + ", ".join(f"`{n}`" for n in permissions["allowed_but_not_registered"])
            )
    except Exception as exc:
        st.error(f"Impossible de récupérer la liste des outils : {describe_error(exc)}")

# --- Diagnostic (palier 2) --------------------------------------------

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
                response = requests.get(f"{BACKEND_URL}/agent/ping-llm", timeout=130)
                response.raise_for_status()
                st.success(f"Agent + LLM joignables : {response.json()}")
            except Exception as exc:
                st.error(f"Agent + LLM : {describe_error(exc)}")
