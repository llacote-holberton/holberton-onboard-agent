"""
Exécuteur : dispatch mécanique des actions déjà approuvées par le backend
(déjà filtrées côté idempotence). Aucun nouvel appel LLM ici.

Contrat consommé par backend/app/services/agent_client.py :
  execute(actions) -> [
      {"action_id": str, "status": "executed"|"error", "result": dict|None, "note": str|None},
      ...
  ]
"""

import os
from fastmcp import Client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8200")
_MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"


async def execute_actions(actions: list[dict]) -> list[dict]:
    results = []
    async with Client(_MCP_ENDPOINT) as mcp_client:
        for action in actions:
            action_id = action["action_id"]
            tool = action["tool"]
            params = action.get("params", {})
            try:
                call_result = await mcp_client.call_tool(tool, params)
                results.append({
                    "action_id": action_id,
                    "status": "executed",
                    "result": call_result.data,
                    "note": None,
                })
            except Exception as exc:
                results.append({
                    "action_id": action_id,
                    "status": "error",
                    "result": None,
                    "note": str(exc),
                })
    return results
