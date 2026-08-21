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

from app.config import AGENT_AI_URL


class AgentAIError(Exception):
    """Raised when the Agent AI actually responded, but with an error
    status -- as opposed to httpx.RequestError (ConnectError,
    TimeoutException, ...), which means the backend couldn't reach the
    agent at all. agent/main.py's /plan and /execute handlers already
    build a clear, human-readable `detail` for every failure mode they
    catch (see their own docstrings, "l'utilisateur doit comprendre CE QUI
    a échoué") -- but a plain `response.raise_for_status()` raises
    httpx.HTTPStatusError BEFORE anyone reads that JSON body, so the
    generic "Server error '503 ...' for url '...'" string was reaching the
    frontend instead (reported live: a clean 503/detail from the agent
    still showed up as a raw technical message in the UI). This exception
    carries the agent's own status_code/detail through unchanged so
    routers/plans.py can forward exactly what the agent said."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def _post(client: httpx.AsyncClient, url: str, json_body: dict) -> httpx.Response:
    """POST and raise AgentAIError (with the agent's own `detail`) on any
    non-2xx response, instead of letting response.raise_for_status() raise
    httpx.HTTPStatusError and discard the response body -- see AgentAIError
    above. httpx.RequestError (agent unreachable, timeout, ...) is not
    caught here and propagates as-is: that's a different failure mode,
    still handled by routers/plans.py's existing `except httpx.HTTPError`
    fallback."""
    response = await client.post(url, json=json_body)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail") or response.text
        except ValueError:
            # Body isn't JSON at all (e.g. the agent process crashed below
            # FastAPI's own exception handlers) -- fall back to raw text
            # rather than raising an unrelated JSONDecodeError here.
            detail = response.text or f"Agent AI returned HTTP {response.status_code} with no detail."
        raise AgentAIError(response.status_code, detail)
    return response


_TIMEOUT = httpx.Timeout(240.0)
# Pushé à 240 (était 120) : /plan peut désormais enchaîner jusqu'à
# _MAX_TURNS=8 tours (exploration + relances successives, voir
# agent/planner.py) -- même avec un modèle chaud (~10-15s/tour), le
# cumul peut dépasser l'ancien budget de 120s sans qu'aucun tour
# individuel ne soit anormalement lent. /execute n'a pas besoin d'un
# budget aussi large (dispatch mécanique, pas de boucle LLM), mais
# partage cette constante par simplicité -- pas de risque, juste une
# limite haute plus généreuse que nécessaire pour ce cas.
_PING_TIMEOUT = httpx.Timeout(10.0)

# ping_llm() specifically waits on a real LLM round trip (agent -> Ollama),
# and agent/main.py's own call to Ollama already allows up to 60s (see
# OLLAMA_API_BASE client in ping-llm). This timeout MUST stay comfortably
# above that, or the backend gives up on the agent before the agent gives
# up on Ollama.
#
# In practice ping_llm() also needs enough RAM for Ollama to actually load
# a model, which turned out not to be a given (OOM-killed even on the
# smallest qwen3 tag, on a 3GB-constrained environment) -- that failure
# mode is independent of this codebase and outside what a longer timeout
# can fix. ping() below exists specifically to decouple "is the agent
# reachable" (what palier 2 needs) from "can this machine run an LLM right
# now" (a separate, later concern).
_PING_LLM_TIMEOUT = httpx.Timeout(90.0)


async def plan(prompt: str) -> dict[str, Any]:
    """Ask the Agent AI to turn a free-text prompt into a list of proposed
    actions. Returns {"actions": [...], "excluded_actions": [...],
    "clarification": str | None, "trace": [...]}:
    - actions: allowed tools the model chose to call.
    - excluded_actions: NOT-allowed tools the model would have called,
      same shape plus a "note" explaining why it can't run (see
      mcp_server/resources.py, agent/planner.py).
    - clarification: the model's own text when neither actions nor
      excluded_actions were produced at all (e.g. off-topic prompt).
    - trace: turn-by-turn planning trace (exploration/proposal/final),
      surfaced in the UI for observability (palier 5) -- "why did the
      agent do that" answerable from the app, not the logs."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await _post(client, f"{AGENT_AI_URL}/plan", {"prompt": prompt})
        data = response.json()
        return {
            "actions": data["actions"],
            "excluded_actions": data.get("excluded_actions", []),
            "clarification": data.get("clarification"),
            "trace": data.get("trace", []),
        }


async def execute(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hand the Agent AI a list of already-approved, already
    idempotency-filtered actions to execute. Purely mechanical dispatch on
    the agent's side -- no new LLM call, see docker-compose.yml's `agent`
    service comment."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await _post(client, f"{AGENT_AI_URL}/execute", {"actions": actions})
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
