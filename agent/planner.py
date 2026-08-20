"""
Planificateur : découvre les tools disponibles via mcp-server (lecture
seule, list_tools() + la resource "config://allowed-tools"), les convertit
au format tool-calling d'Ollama, et les propose au modèle avec le prompt
utilisateur. N'exécute rien.

Contrat consommé par backend/app/services/agent_client.py :
  build_plan(prompt) -> [{"tool": str, "params": dict, "summary": str}, ...]

Extension "tools autorisés" : le modèle ne peut techniquement appeler que
les tools listés comme autorisés par la resource MCP dédiée (paramètre
`tools=` de l'appel Ollama, restreint) -- mais il connaît aussi les noms
et descriptions des tools existants mais non autorisés (glissés en texte
dans le system prompt), pour pouvoir le dire explicitement si la demande
de l'utilisateur en aurait besoin, plutôt que de rester silencieux ou
d'appeler un tool autorisé à la place par défaut.
"""

import json
import os
import httpx
from fastmcp import Client
from datetime import date

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8200")
_MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

_BASE_SYSTEM_PROMPT = (
    "Tu es un agent qui prépare l'arrivée de nouveaux collaborateurs. "
    "À partir de l'intention de l'utilisateur, propose les actions pertinentes "
    "en appelant les outils disponibles. Tu ne dois JAMAIS exécuter d'action "
    "toi-même : tu proposes uniquement un plan, qui sera validé par un humain "
    "avant toute exécution."
)

_SUMMARY_TEMPLATES = {
    "create_onboarding_issue": "Créer le ticket onboarding pour {employee_name}",
    "create_employee_record": "Créer la fiche employé pour {name} ({role})",
    "send_welcome_message": "Envoyer un message d'accueil ({channel}) à l'équipe {team} pour {employee_name}",
    "generate_handbook": "Générer le document '{template}'",
    "create_calendar_event": "Créer l'événement '{title}'",
}

# Fonctions de compensation ("undo"), jamais exposées comme appelables au
# LLM au moment du plan (voir tools/tracker.py::close_onboarding_issue) --
# orthogonal à la notion d'"autorisation" ci-dessous : une fonction interne
# reste interne même si ALLOWED_TOOLS la mentionnerait par erreur.
_INTERNAL_ONLY_TOOLS = {
    "close_onboarding_issue",
    "delete_employee_record",
}


def _summarize(tool_name: str, params: dict) -> str:
    template = _SUMMARY_TEMPLATES.get(tool_name)
    if template:
        try:
            return template.format(**params)
        except (KeyError, IndexError):
            pass
    if params:
        readable = ", ".join(f"{k}: {v}" for k, v in params.items())
        return f"{tool_name} ({readable})"
    return f"Exécuter {tool_name}"


def _to_ollama_tool(t) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description or "",
            "parameters": t.inputSchema,
        },
    }


async def _discover_tool_permissions() -> tuple[list, dict]:
    """Retourne (tools_mcp_bruts, permissions), permissions étant le
    contenu de la resource "config://allowed-tools" (allowed /
    registered_but_not_allowed / allowed_but_not_registered)."""
    async with Client(_MCP_ENDPOINT) as mcp_client:
        tools = await mcp_client.list_tools()
        resource_result = await mcp_client.read_resource("config://allowed-tools")

    # read_resource() renvoie une liste de contenus ; on prend le premier
    # bloc texte/JSON, seul bloc produit par notre resource.
    permissions = json.loads(resource_result[0].text)

    return tools, permissions


async def _build_prompt_context(prompt: str) -> tuple[list[dict], str]:
    """Sépare les tools fonctionnels (hors fonctions de compensation
    internes) en deux groupes selon la resource "config://allowed-tools",
    construit la liste réellement invocable par Ollama (autorisés
    seulement) et le system prompt qui mentionne aussi les non-autorisés
    en texte, pour que le modèle puisse les nommer sans pouvoir les
    appeler."""
    tools, permissions = await _discover_tool_permissions()

    functional_tools = {t.name: t for t in tools if t.name not in _INTERNAL_ONLY_TOOLS}
    allowed_names = set(permissions["allowed"]) & functional_tools.keys()
    blocked_names = functional_tools.keys() - allowed_names

    ollama_tools = [_to_ollama_tool(functional_tools[name]) for name in allowed_names]

    system_prompt = _BASE_SYSTEM_PROMPT + (
        f"\n\nNous sommes le {date.today().isoformat()}. "
        "Quand une date est relative (\"lundi prochain\", \"dans 2 semaines\"), "
        "calcule la date exacte au format YYYY-MM-DD avant d'appeler un outil."
    )

    if blocked_names:
        blocked_descriptions = "\n".join(
            f"- {name} : {functional_tools[name].description or '(pas de description)'}"
            for name in sorted(blocked_names)
        )
        system_prompt += (
            "\n\nCertains outils existent mais ne sont PAS autorisés actuellement "
            "(tu ne peux PAS les appeler, ils ne te sont même pas proposés comme "
            f"appelables) :\n{blocked_descriptions}\n\n"
            "Si la demande de l'utilisateur nécessite un de ces outils non "
            "autorisés, NE réponds PAS en appelant un autre outil à la place, "
            "et ne reste PAS silencieux : indique clairement, en texte, quel "
            "outil non autorisé serait nécessaire et pourquoi."
        )

    return ollama_tools, system_prompt


async def build_plan(prompt: str) -> tuple[list[dict], str | None]:
    """Retourne (actions, notice) -- notice est le texte du modèle quand il
    n'a proposé aucune action (ex: outil non autorisé nécessaire, ou
    information manquante), sinon None."""
    ollama_tools, system_prompt = await _build_prompt_context(prompt)

    async with httpx.AsyncClient(timeout=110) as client:
        r = await client.post(
            f"{OLLAMA_API_BASE}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "tools": ollama_tools,
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

    notice = None
    if not actions:
        notice = data.get("message", {}).get("content") or None

    return actions, notice
