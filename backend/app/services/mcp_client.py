"""
HTTP client for the MCP server, used ONLY for cancellation (undo) -- see
ARCHITECTURE.md "Décision structurante n°2": the backend calls the MCP
server directly for undo, no need to re-plan through the agent.

ASSUMPTION, NOT YET CONFIRMED: same caveat as agent_client.py -- this
contract has not been checked against the real mcp-server implementation.

Assumed contract:
  POST {MCP_SERVER_URL}/undo
    request:  {"tool": str, "params": dict, "result": dict | None}
    response: {"status": "undone", "note": str | None}
"""

from typing import Any

import httpx

from app.config import MCP_SERVER_URL

_TIMEOUT = httpx.Timeout(30.0)


async def undo(tool: str, params: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{MCP_SERVER_URL}/undo",
            json={"tool": tool, "params": params, "result": result},
        )
        response.raise_for_status()
        return response.json()
