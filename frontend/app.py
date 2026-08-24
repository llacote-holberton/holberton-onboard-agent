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

# RECONCILIATION STEP 3bis (2026-08-21, Laurent), puis renommée
# LLM_CALL_TIMEOUT_SECONDS (2026-08-21, LLM CONFIGURATION -- AGNOSTIQUE)
# -- outermost layer of the coordinated timeout chain (frontend ->
# backend -> agent -> LLM provider, whichever LLM_MODEL_NAME designates).
# Reads the SAME LLM_CALL_TIMEOUT_SECONDS env var as agent/planner.py and
# backend/app/config.py (see docker-compose.yml, this service's
# `environment:` block) and adds this layer's own +30s margin (base +15
# for the backend layer it wraps, +15 more for this one) -- one setting
# to change for the whole chain instead of three. See planner.py's
# _LLM_CALL_TIMEOUT comment for the full rationale. Still reads the old
# name (OLLAMA_CALL_TIMEOUT_SECONDS) as a fallback for a not-yet-updated
# .env.
_PLAN_GENERATION_TIMEOUT = (
    int(os.environ.get("LLM_CALL_TIMEOUT_SECONDS", os.environ.get("OLLAMA_CALL_TIMEOUT_SECONDS", "110"))) + 30
)

# RECONCILIATION 2026-08-20 (Laurent) -- must match backend/app/config.py::
# FILE_GENERATING_TOOLS exactly; kept as a separate constant here rather
# than fetched from the backend because it only decides which actions get
# a download button, not any correctness-critical behaviour.
_FILE_GENERATING_TOOLS = {"generate_handbook", "create_calendar_event"}

# Libellés dédiés au bouton de téléchargement -- action['summary'] (voir
# agent/planner.py::_SUMMARY_TEMPLATES) est rédigé au futur/impératif pour
# la checklist PRE-exécution ("Générer le document...", "Créer
# l'événement..."), ce qui n'a plus de sens une fois l'action déjà
# exécutée : le fichier existe déjà, le bouton ne fait que le télécharger.
# Même paramètres que _SUMMARY_TEMPLATES (title/template), juste le verbe
# de corrigé -- dupliqué ici pour la même raison que _FILE_GENERATING_TOOLS
# juste au-dessus (pas de dépendance au backend pour un simple libellé).
_DOWNLOAD_LABELS = {
    "generate_handbook": "Télécharger le document '{template}'",
    "create_calendar_event": "Télécharger l'événement '{title}'",
}


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


def render_downloadable_files(actions: list[dict]) -> None:
    """RECONCILIATION 2026-08-20 (Laurent) -- one download button per
    executed file-generating action (see backend/app/routers/actions.py::
    download_action_file). BACKEND_URL only resolves inside the docker
    network, not from the end user's browser, so the frontend must fetch
    the bytes itself and hand them to st.download_button rather than link
    directly to the backend."""
    downloadable = [
        a for a in actions if a["tool"] in _FILE_GENERATING_TOOLS and a["status"] == "executed"
    ]
    if not downloadable:
        return

    st.markdown("**📎 Fichiers générés**")
    for action in downloadable:
        try:
            response = requests.get(f"{BACKEND_URL}/actions/{action['id']}/download", timeout=30)
            response.raise_for_status()
            filename = None
            disposition = response.headers.get("content-disposition", "")
            if "filename=" in disposition:
                filename = disposition.split("filename=")[-1].strip('"')
            label_template = _DOWNLOAD_LABELS.get(action["tool"])
            try:
                label = label_template.format(**action["params"]) if label_template else action["summary"]
            except (KeyError, IndexError):
                # Paramètre attendu manquant (tool ajouté à _DOWNLOAD_LABELS
                # sans le bon nom de paramètre, ou schéma modifié côté
                # mcp-server) -- ne jamais faire planter l'affichage du
                # bouton pour un simple problème de libellé.
                label = action["summary"]
            st.download_button(
                f"⬇️ {label}",
                data=response.content,
                file_name=filename or f"{action['id']}.bin",
                mime=response.headers.get("content-type", "application/octet-stream"),
                key=f"download_{action['id']}",
            )
        except Exception as exc:
            st.caption(f"⚠️ Fichier de « {action['summary']} » indisponible : {describe_error(exc)}")


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
            # See _PLAN_GENERATION_TIMEOUT above. dev_laurent previously
            # had a hardcoded 60s here (too low -- would fire before the
            # backend's own 120s timeout even had a chance to);
            # Feature/palier3 had 150s (close, but picked independently of
            # the rest of the chain rather than derived from it).
            response = requests.post(
                f"{BACKEND_URL}/plans", json={"prompt": prompt}, timeout=_PLAN_GENERATION_TIMEOUT
            )
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

                    # CORRECTIF (2026-08-24, Laurent) : timeout en dur (60s)
                    # remplacé par _PLAN_GENERATION_TIMEOUT -- l'exécution
                    # passe par la même chaîne backend -> agent -> MCP que
                    # /plan (dispatch synchrone des actions), autorisée
                    # côté agent jusqu'à AGENT_PLAN_TIMEOUT_SECONDS (voir
                    # backend/app/config.py). Un timeout frontend plus
                    # court pouvait afficher une erreur alors que
                    # l'exécution était encore légitimement en cours.
                    execution = requests.post(
                        f"{BACKEND_URL}/plans/{plan['id']}/execute", timeout=_PLAN_GENERATION_TIMEOUT
                    )
                    execution.raise_for_status()
                    results = execution.json()

                    executed_count = sum(1 for r in results if r["status"] == "executed")
                    failed_count = len(results) - executed_count
                    st.success(f"{executed_count} action(s) exécutée(s) sur {len(results)}.")
                    if failed_count:
                        # CORRECTIF : un échec partiel (tool non autorisé,
                        # erreur métier d'un tool, ...) était auparavant
                        # invisible tant qu'on n'ouvrait pas "Traçabilité de
                        # ce plan" -- le seul retour visible était le
                        # st.success ci-dessus, silencieux sur les échecs.
                        st.warning(
                            f"⚠️ {failed_count} action(s) n'ont pas pu être "
                            "exécutée(s) -- voir « Traçabilité de ce plan » "
                            "ci-dessous pour le détail de chaque échec."
                        )
                    st.session_state.trace = fetch_audit_trace(plan["id"])

                    # BUG FIX 2026-08-20 (Laurent) -- st.session_state.plan
                    # was never refreshed after execution: it still held the
                    # pre-execution snapshot (every action "approved", no
                    # result), so downstream UI (download buttons here, but
                    # also just re-reading the plan) never saw the real
                    # post-execution status/result. Re-fetch before rerun.
                    refreshed = requests.get(f"{BACKEND_URL}/plans/{plan['id']}", timeout=15)
                    refreshed.raise_for_status()
                    st.session_state.plan = refreshed.json()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Échec de l'exécution : {describe_error(exc)}")

        render_downloadable_files(plan["actions"])

        if st.session_state.trace is not None:
            st.subheader("Traçabilité de ce plan")
            st.caption(f"Plan `{plan['id']}` — du plus ancien au plus récent (GET /audit?plan_id=...).")
            render_audit_trace(st.session_state.trace)
            if st.button("Rafraîchir la trace"):
                st.session_state.trace = fetch_audit_trace(plan["id"])
                st.rerun()

    # --- Observabilité (portage 2026-08-24, Laurent, depuis db8b25a de
    # feature/palier5 -- Hugo) : "pourquoi l'agent a fait ça", vérifiable
    # dans l'app -- pas seulement dans les logs Docker. Volontairement HORS
    # du bloc "else" ci-dessus (contrairement au premier portage de cette
    # trace) : un plan "blocked" (garde-fou pré-plan déclenché, voir
    # agent/planner.py::_looks_like_prompt_injection/_strip_emojis) a par
    # définition actions=[] ET excluded_actions=[], donc tombe dans la
    # branche "clarification" ci-dessus -- sans ce déplacement, sa trace
    # (kind="blocked") ne serait jamais visible dans l'UI, ce qui viderait
    # le mécanisme de son intérêt (trace d'audit exploitable).
    #
    # "narration" est un kind propre à dev_laurent, absent de la version
    # d'origine de Hugo : il correspond à la relance ciblée de
    # _FIRST_TURN_NARRATION_NUDGE (voir agent/planner.py), qui n'existe pas
    # sur feature/palier5. "blocked" (2026-08-24, portage/extension du
    # commit local 1c2072c8 de Laurent -- jamais poussé sur cette branche)
    # marque un rejet pré-plan : injection détectée, ou prompt réduit à des
    # emojis/symboles après filtrage.
    _KIND_ICONS = {
        "exploration": "🔎",
        "proposal": "✅",
        "final": "🏁",
        "narration": "💬",
        "blocked": "🛡️",
    }
    _KIND_LABELS = {
        "exploration": "Consultation",
        "proposal": "Proposition",
        "final": "Décision finale",
        "narration": "Relance (narration)",
        "blocked": "Rejeté avant appel au modèle",
    }
    with st.expander("🔍 Pourquoi ce plan ?", expanded=False):
        if plan.get("trace"):
            for entry in plan["trace"]:
                icon = _KIND_ICONS.get(entry["kind"], "•")
                label = _KIND_LABELS.get(entry["kind"], entry["kind"])
                tool_part = f" `{entry['tool']}`" if entry.get("tool") else ""
                st.write(f"{icon} **Tour {entry['turn']}** · {label}{tool_part}")
                st.caption(entry["detail"])
        else:
            st.caption("Aucune trace disponible pour ce plan.")

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
                # CORRECTIF (24/08, Laurent) : réutilise _PLAN_GENERATION_TIMEOUT
                # (ci-dessus) au lieu d'une valeur en dur -- un seul appel LLM
                # dans les deux cas, même marge nécessaire. Ancienne bogue :
                # 130 puis 270 codés en clair ici, jamais mis à jour en même
                # temps que LLM_CALL_TIMEOUT_SECONDS.
                response = requests.get(f"{BACKEND_URL}/agent/ping-llm", timeout=_PLAN_GENERATION_TIMEOUT)
                response.raise_for_status()
                st.success(f"Agent + LLM joignables : {response.json()}")
            except Exception as exc:
                st.error(f"Agent + LLM : {describe_error(exc)}")
