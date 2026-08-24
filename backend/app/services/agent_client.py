"""
HTTP client for the Agent AI service: planning + execution of approved
actions (see ARCHITECTURE.md "Décision structurante n°2").

ASSUMPTION, NOT YET CONFIRMED: the request/response shapes below are what
this backend expects. They have not been checked against Hugo's actual
Agent AI implementation. Treat this file as a proposed contract, not a
verified integration -- align it with the real Agent AI endpoints before
relying on it end to end.

Assumed contract:
  POST {AGENT_AI_URL}/plan
    request:  {"prompt": str}
    response: {"actions": [{"tool": str, "params": dict, "summary": str}, ...]}

  POST {AGENT_AI_URL}/execute
    request:  {"actions": [{"action_id": str, "tool": str, "params": dict}, ...]}
    response: {"results": [
        {"action_id": str, "status": "executed", "result": dict | None, "note": str | None},
        ...
    ]}
"""

from typing import Any

import httpx

from app.config import AGENT_AI_URL, AGENT_PLAN_TIMEOUT_SECONDS

# RECONCILIATION STEP 3 (2026-08-21, Laurent), then 3bis -- coordinated
# timeout chain across all three HTTP layers (frontend -> backend ->
# agent -> LLM provider, whichever LLM_MODEL_NAME designates). This is
# the middle layer, wrapping agent/planner.py's per-LLM-call timeout:
# AGENT_PLAN_TIMEOUT_SECONDS (from app.config) is derived from the SAME
# LLM_CALL_TIMEOUT_SECONDS env var the agent reads, +15s margin -- see
# app/config.py and planner.py's _LLM_CALL_TIMEOUT comment for the full
# chain and its known blind spot (this margin covers one slow call
# comfortably, not a pathological multi-turn worst case -- build_plan()
# can chain up to _MAX_TURNS calls).
#
# Also (still) used by execute() below, even though execute() makes no
# LLM call at all -- kept shared with plan() for simplicity, not split
# into its own (shorter) timeout for now.
_TIMEOUT = httpx.Timeout(AGENT_PLAN_TIMEOUT_SECONDS)
_PING_TIMEOUT = httpx.Timeout(10.0)

# ping_llm() specifically waits on a real LLM round trip (agent -> LLM
# provider), exactly one call -- same cost profile as a single turn of
# /plan. CORRECTIF (24/08, Laurent) : ne plus avoir une valeur en dur ici
# (ancienne bogue -- 90.0 puis 260.0 codés en clair, à corriger à la main
# à chaque fois qu'on veut donner plus de temps à une machine lente),
# réutiliser directement AGENT_PLAN_TIMEOUT_SECONDS -- déjà importé,
# déjà = LLM_CALL_TIMEOUT_SECONDS + 15s. Ça reste une chaîne SÉPARÉE de
# /plan au sens fonctionnel (ping() plus bas décorrèle exprès "l'agent
# répond" de "le LLM répond") -- seule la VALEUR du timeout est
# mutualisée, pas la sémantique de l'endpoint.
#
# ping_llm() a aussi besoin d'assez de RAM pour qu'Ollama charge un
# modèle, ce qui n'est pas garanti (OOM-killed observé même sur le plus
# petit tag qwen3, sur un environnement contraint à 3 Go) -- ce mode de
# panne est indépendant de ce code et hors de portée d'un timeout plus
# long, quelle que soit sa valeur. ping() ci-dessous existe justement pour
# découpler "l'agent est joignable" (ce dont palier 2 a besoin) de "cette
# machine peut faire tourner un LLM maintenant" (un souci séparé, plus tardif).
_PING_LLM_TIMEOUT = httpx.Timeout(AGENT_PLAN_TIMEOUT_SECONDS)


class AgentAIError(httpx.HTTPError):
    """DURCISSEMENT (2026-08-21, Laurent) -- raised instead of plain
    httpx.HTTPStatusError when the Agent AI responds with an error status.
    Subclasses httpx.HTTPError so existing `except httpx.HTTPError` call
    sites (see routers/plans.py) keep catching it unchanged even where it
    isn't caught explicitly, but carries the agent's own already-human-
    readable `detail` message (see agent/main.py::_describe_llm_error)
    instead of the generic status line httpx.HTTPStatusError.__str__()
    produces by default (e.g. "502 Server Error: Bad Gateway for url:
    ...", which silently drops the actually useful explanation of WHY --
    missing/invalid API key, network unreachable, timeout... -- see the
    DURCISSEMENT palier, scénario 3: "je coupe le réseau / fausse clé,
    l'app doit le dire.")

    CORRECTIF (2026-08-24, Laurent) -- status_code et detail gardés comme
    deux attributs SÉPARÉS plutôt que fondus dans une seule chaîne
    ("Agent AI a répondu 503 : ..."). Avant ce correctif, routers/plans.py
    ne catchait cette exception qu'implicitement via `except
    httpx.HTTPError`, qui renvoie TOUJOURS 502 au navigateur quel que soit
    le vrai code -- un vrai 503/504 de l'agent devenait un 502 générique,
    et le message affiché doublait le préfixe ("Agent AI /plan call
    failed: Agent AI a répondu 503 : ..."). Voir routers/plans.py pour le
    `except AgentAIError` désormais explicite qui répercute exc.status_code
    et exc.detail tels quels."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _raise_for_status_with_detail(response: httpx.Response) -> None:
    """Like response.raise_for_status(), but prefers the agent's own JSON
    `detail` body (already a clear, specific explanation) over the
    generic status line when one is present."""
    if response.status_code < 400:
        return
    detail = None
    try:
        detail = response.json().get("detail")
    except ValueError:
        pass
    if detail:
        raise AgentAIError(response.status_code, detail)
    response.raise_for_status()  # fallback: no JSON detail, generic message


async def plan(prompt: str) -> dict[str, Any]:
    """Ask the Agent AI to turn a free-text prompt into a list of proposed
    actions. Returns {"actions": [...], "excluded_actions": [...],
    "clarification": str | None}:
    - actions: allowed tools the model chose to call.
    - excluded_actions: NOT-allowed tools the model would have called,
      same shape plus a "note" explaining why it can't run (see
      mcp_server/resources.py, agent/planner.py).
    - clarification: the model's own text when neither actions nor
      excluded_actions were produced at all (e.g. off-topic prompt)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(f"{AGENT_AI_URL}/plan", json={"prompt": prompt})
        _raise_for_status_with_detail(response)
        data = response.json()
        return {
            "actions": data["actions"],
            "excluded_actions": data.get("excluded_actions", []),
            "clarification": data.get("clarification"),
        }


async def execute(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hand the Agent AI a list of already-approved, already
    idempotency-filtered actions to execute. Purely mechanical dispatch on
    the agent's side -- no new LLM call, see docker-compose.yml's `agent`
    service comment."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(f"{AGENT_AI_URL}/execute", json={"actions": actions})
        _raise_for_status_with_detail(response)
        return response.json()["results"]


async def ping() -> dict[str, Any]:
    """Lightweight connectivity check (backend -> Agent AI), with NO LLM
    call and no meaningful memory footprint -- calls the agent's GET /ping
    (see agent_plan_execute_proposal.py, a 3-line addition for Hugo). This
    is the palier 2 gate: proving the backend can reach and talk to the
    agent process itself, independent of whether the machine has enough
    RAM to also run Ollama right now."""
    async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
        response = await client.get(f"{AGENT_AI_URL}/ping")
        response.raise_for_status()
        return response.json()


async def ping_llm() -> dict[str, Any]:
    """Heavier connectivity check: also exercises the agent -> Ollama LLM
    round trip (the agent's pre-existing GET /ping-llm). Needs enough
    memory for Ollama to actually load the configured model -- expect this
    to fail/OOM under a tight memory budget even for a small model. Not
    required for palier 2 -- see ping() above."""
    async with httpx.AsyncClient(timeout=_PING_LLM_TIMEOUT) as client:
        response = await client.get(f"{AGENT_AI_URL}/ping-llm")
        response.raise_for_status()
        return response.json()


async def tool_permissions() -> dict[str, Any]:
    """Read-only: forwards the agent's GET /tools/permissions, itself a
    passthrough of mcp-server's "config://allowed-tools" MCP resource (see
    mcp_server/resources.py). No LLM call -- same cheap connectivity
    profile as ping(), not ping_llm()."""
    async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
        response = await client.get(f"{AGENT_AI_URL}/tools/permissions")
        response.raise_for_status()
        return response.json()
