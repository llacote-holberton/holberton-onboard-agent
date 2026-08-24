"""
Exécuteur : dispatch mécanique des actions déjà approuvées par le backend
(déjà filtrées côté idempotence). Aucun nouvel appel LLM ici.

Défense en profondeur : revérifie l'autorisation de chaque tool contre la
resource MCP "config://allowed-tools" avant d'exécuter, même si /plan ne
propose déjà que des actions autorisées comme "actions" -- protège contre
un appel direct à /execute qui contournerait /plan.

Contrat consommé par backend/app/services/agent_client.py :
  execute(actions) -> [
      {"action_id": str, "status": "executed"|"error", "result": dict|None, "note": str|None},
      ...
  ]
"""

import json
import os
import re
from fastmcp import Client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8200")
_MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

# CORRECTIF (2026-08-24, Laurent, portage de feature/palier5) -- FastMCP
# préfixe systématiquement ses erreurs par "Error calling tool '<nom>': "
# avant le vrai message métier -- un détail d'implémentation du protocole,
# pas une information utile pour l'utilisateur final ("retouches
# utilisateur" : autant de messages non techniques que possible). On
# retire ce préfixe pour ne garder que le message métier, déjà clair par
# ailleurs (ex: "Équipe inconnue : ... vérifiez le nom de l'équipe.",
# voir mcp_server/tools/mailbox.py::_resolve_recipients).
_TOOL_ERROR_PREFIX = re.compile(r"^Error calling tool '[^']+':\s*")


def _humanize_error(exc: Exception) -> str:
    return _TOOL_ERROR_PREFIX.sub("", str(exc))


async def execute_actions(actions: list[dict]) -> list[dict]:
    results = []
    async with Client(_MCP_ENDPOINT) as mcp_client:
        resource_result = await mcp_client.read_resource("config://allowed-tools")
        allowed_names = set(json.loads(resource_result[0].text)["allowed"])

        for action in actions:
            action_id = action["action_id"]
            tool = action["tool"]
            params = action.get("params", {})

            if tool not in allowed_names:
                results.append({
                    "action_id": action_id,
                    "status": "error",
                    "result": None,
                    "note": (
                        f"Action non autorisée : '{tool}' n'est pas dans la "
                        "liste des outils autorisés actuellement."
                    ),
                })
                continue

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
                    "note": _humanize_error(exc),
                })
    return results
