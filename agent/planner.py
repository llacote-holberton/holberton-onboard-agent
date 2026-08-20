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
    "À partir de l'intention de l'utilisateur, propose TOUTES les actions "
    "pertinentes en appelant les outils disponibles -- une intention "
    "d'onboarding implique souvent plusieurs actions à la fois (créer un "
    "ticket, notifier l'équipe, générer un document, etc.), pas une seule "
    "par défaut. Tu ne dois JAMAIS exécuter d'action toi-même : tu "
    "proposes uniquement un plan, qui sera validé par un humain avant "
    "toute exécution.\n\n"
    "Distingue deux types de paramètres :\n"
    "- Paramètres d'IDENTIFICATION (équipe, date, email, identifiant) : "
    "ne les invente jamais au hasard, mais déduis-les du contexte quand "
    "c'est raisonnable (ex: l'équipe mentionnée pour une personne "
    "s'applique à toutes les actions concernant cette même personne).\n"
    "- Paramètres de CONTENU (checklist, titre, corps de message, canal "
    "de notification) : choisis une valeur par défaut raisonnable plutôt "
    "que de sauter l'outil, l'humain validera de toute façon avant "
    "exécution. Pour le paramètre channel d'un message d'accueil, "
    "utilise 'team' par défaut sauf indication contraire explicite."
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


async def _build_prompt_context(prompt: str) -> tuple[list[dict], str, set[str]]:
    """Donne TOUS les tools fonctionnels (autorisés + non autorisés) comme
    choix possibles au modèle -- /plan n'exécute jamais rien, donc aucun
    risque à le laisser "choisir" un tool non autorisé. Le tri
    autorisé/exclu se fait après coup, de façon déterministe, dans
    build_plan() ci-dessous, plutôt que de compter sur le modèle pour
    décrire correctement en texte ce qu'il n'a pas pu faire."""
    tools, permissions = await _discover_tool_permissions()

    functional_tools = {t.name: t for t in tools if t.name not in _INTERNAL_ONLY_TOOLS}
    allowed_names = set(permissions["allowed"]) & functional_tools.keys()

    ollama_tools = [_to_ollama_tool(t) for t in functional_tools.values()]

    system_prompt = _BASE_SYSTEM_PROMPT + (
        f"\n\nNous sommes le {date.today().isoformat()}. "
        "Quand une date est relative (\"lundi prochain\", \"dans 2 semaines\"), "
        "calcule la date exacte au format YYYY-MM-DD avant d'appeler un outil."
    )

    return ollama_tools, system_prompt, allowed_names


async def build_plan(prompt: str) -> tuple[list[dict], list[dict], str | None]:
    """Retourne (actions, excluded_actions, notice).

    - actions : outils autorisés que le modèle a choisi d'appeler.
    - excluded_actions : outils NON autorisés que le modèle aurait appelés
      si rien ne l'en empêchait -- même format que actions, plus une note
      expliquant pourquoi ce n'est pas exécutable actuellement.
    - notice : texte du modèle quand ni l'un ni l'autre n'a été produit
      (ex: demande hors-scope, aucun outil pertinent du tout)."""
    ollama_tools, system_prompt, allowed_names = await _build_prompt_context(prompt)

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
                "options": {"temperature": 0.1},
            },
        )
        r.raise_for_status()
        data = r.json()

    tool_calls = data.get("message", {}).get("tool_calls", [])

    actions = []
    excluded_actions = []
    for call in tool_calls:
        fn = call["function"]
        tool_name = fn["name"]
        params = fn.get("arguments", {})
        summary = _summarize(tool_name, params)

        if tool_name in allowed_names:
            actions.append({"tool": tool_name, "params": params, "summary": summary})
        else:
            excluded_actions.append({
                "tool": tool_name,
                "params": params,
                "summary": summary,
                "note": (
                    "Action non autorisée pour le moment -- contactez "
                    "l'administrateur pour l'activer."
                ),
            })

    notice = None
    if not actions and not excluded_actions:
        notice = data.get("message", {}).get("content") or None

    return actions, excluded_actions, notice
