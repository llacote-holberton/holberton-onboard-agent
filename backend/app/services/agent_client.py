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

_TIMEOUT = httpx.Timeout(30.0)


async def plan(prompt: str) -> list[dict[str, Any]]:
    """Ask the Agent AI to turn a free-text prompt into a list of proposed
    actions. Returns the raw action dicts (tool/params/summary); the caller
    persists them as Action rows."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(f"{AGENT_AI_URL}/plan", json={"prompt": prompt})
        response.raise_for_status()
        return response.json()["actions"]


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
    """Basic end-to-end connectivity check (backend -> Agent AI -> Ollama),
    with no project-specific logic involved -- calls the agent's existing
    /ping-llm endpoint, which already exists on Hugo's side today. This is
    what unblocks palier 2: proving the backend can actually reach and
    talk to the agent, ahead of the real /plan and /execute contract
    above (which the agent doesn't implement yet)."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(f"{AGENT_AI_URL}/ping-llm")
        response.raise_for_status()
        return response.json()
