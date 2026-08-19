"""
Planificateur : découvre les tools disponibles via mcp-server (lecture
seule, list_tools()), les convertit au format tool-calling d'Ollama, et
les propose au modèle avec le prompt utilisateur. N'exécute rien.

Synthèse entre la proposition de Pierre (découverte dynamique des tools,
source de vérité unique côté mcp-server) et le tool calling natif d'Ollama
(plus fiable qu'un format JSON généré librement) -- à valider ensemble
avant de merger, ce fichier remplace le contenu envoyé par Pierre pour
/plan uniquement.

Contrat consommé par backend/app/services/agent_client.py :
  build_plan(prompt) -> [{"tool": str, "params": dict, "summary": str}, ...]
"""

import os
import httpx
from fastmcp import Client
from datetime import date

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

# Pas de suffixe /mcp dans la variable elle-même (convention alignée sur
# celle de Pierre / docker-compose.yml) -- on l'ajoute ici.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8200")
_MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

SYSTEM_PROMPT = (
    f"Nous sommes le {date.today().isoformat()}. "
    "Tu es un agent qui prépare l'arrivée de nouveaux collaborateurs. "
    "À partir de l'intention de l'utilisateur, propose les actions pertinentes "
    "en appelant les outils disponibles. Tu ne dois JAMAIS exécuter d'action "
    "toi-même : tu proposes uniquement un plan, qui sera validé par un humain "
    "avant toute exécution."
)

# Résumés lisibles pour l'écran d'approbation. Légère duplication des noms
# de tools (le set réel reste découvert dynamiquement) -- acceptable tant
# qu'on a 5 tools fixes, à revoir si le catalogue devient très dynamique.
_SUMMARY_TEMPLATES = {
    "create_onboarding_issue": "Créer le ticket onboarding pour {employee_name}",
    "create_employee_record": "Créer la fiche employé pour {name} ({role})",
    "send_welcome_message": "Envoyer un message d'accueil ({channel}) à l'équipe {team} pour {employee_name}",
    "generate_handbook": "Générer le document '{template}'",
    "create_calendar_event": "Créer l'événement '{title}'",
}


def _summarize(tool_name: str, params: dict) -> str:
    template = _SUMMARY_TEMPLATES.get(tool_name)
    if template:
        try:
            return template.format(**params)
        except (KeyError, IndexError):
            pass
    # Fallback si le template ne correspond plus aux vrais paramètres du
    # tool (ex: signature modifiée par un·e coéquipier·ère) -- affiche les
    # paramètres bruts plutôt qu'un nom de tool sec et peu lisible.
    if params:
        readable = ", ".join(f"{k}: {v}" for k, v in params.items())
        return f"{tool_name} ({readable})"
    return f"Exécuter {tool_name}"


async def _discover_tools() -> list[dict]:
    """Lecture seule -- aucun effet de bord. Convertit le schéma MCP
    (déjà en JSON Schema) au format tool-calling d'Ollama."""
    async with Client(_MCP_ENDPOINT) as mcp_client:
        tools = await mcp_client.list_tools()

    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema,
            },
        }
        for t in tools
    ]


async def build_plan(prompt: str) -> list[dict]:
    tools = await _discover_tools()

    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            f"{OLLAMA_API_BASE}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "tools": tools,
                "think": False,
                "stream": False,
            },
        )
        r.raise_for_status()
        data = r.json()

    tool_calls = data.get("message", {}).get("tool_calls", [])

    actions = []
    for call in tool_calls:
        fn = call["function"]
        tool_name = fn["name"]
        params = fn.get("arguments", {})
        actions.append({
            "tool": tool_name,
            "params": params,
            "summary": _summarize(tool_name, params),
        })

    return actions
