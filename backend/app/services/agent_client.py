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
# agent -> Ollama). This is the middle layer, wrapping agent/planner.py's
# per-Ollama-call timeout: AGENT_PLAN_TIMEOUT_SECONDS (from app.config)
# is derived from the SAME OLLAMA_CALL_TIMEOUT_SECONDS env var the agent
# reads, +15s margin -- see app/config.py and planner.py's
# _OLLAMA_CALL_TIMEOUT comment for the full chain and its known blind
# spot (this margin covers one slow call comfortably, not a pathological
# multi-turn worst case -- build_plan() can chain up to _MAX_TURNS calls).
#
# Also (still) used by execute() below, even though execute() makes no
# LLM call at all -- kept shared with plan() for simplicity, not split
# into its own (shorter) timeout for now.
_TIMEOUT = httpx.Timeout(AGENT_PLAN_TIMEOUT_SECONDS)
_PING_TIMEOUT = httpx.Timeout(10.0)

# ping_llm() specifically waits on a real LLM round trip (agent -> Ollama),
# and agent/main.py's own call to Ollama already allows up to 60s (see
# OLLAMA_API_BASE client in ping-llm). This timeout MUST stay comfortably
# above that, or the backend gives up on the agent before the agent gives
# up on Ollama. (Separate, independent chain from the /plan one above --
# a lightweight health check, not a real plan generation.)
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
    "clarification": str | None}:
    - actions: allowed tools the model chose to call.
    - excluded_actions: NOT-allowed tools the model would have called,
      same shape plus a "note" explaining why it can't run (see
      mcp_server/resources.py, agent/planner.py).
    - clarification: the model's own text when neither actions nor
      excluded_actions were produced at all (e.g. off-topic prompt)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(f"{AGENT_AI_URL}/plan", json={"prompt": prompt})
        response.raise_for_status()
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
        response.raise_for_status()
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
