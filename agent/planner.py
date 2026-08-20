"""
Planificateur : découvre les tools disponibles via mcp-server (lecture
seule, list_tools() + la resource "config://allowed-tools"), les convertit
au format tool-calling d'Ollama, et les propose au modèle avec le prompt
utilisateur. N'exécute AUCUNE action à effet de bord.

Contrat consommé par backend/app/services/agent_client.py :
  build_plan(prompt) -> [{"tool": str, "params": dict, "summary": str}, ...]

Extension "tools autorisés" : le modèle ne peut techniquement appeler que
les tools listés comme autorisés par la resource MCP dédiée (paramètre
`tools=` de l'appel Ollama, restreint) -- mais il connaît aussi les noms
et descriptions des tools existants mais non autorisés (glissés en texte
dans le system prompt), pour pouvoir le dire explicitement si la demande
de l'utilisateur en aurait besoin, plutôt que de rester silencieux ou
d'appeler un tool autorisé à la place par défaut.

Extension "boucle d'itération" (palier 4) : certains tools sont marqués
EXPLORATOIRES (_EXPLORATORY_TOOLS) -- en lecture seule, sans effet de
bord (ex: list_teams). Si le modèle les appelle, on les exécute
immédiatement nous-mêmes et on renvoie le résultat dans la conversation,
puis on rappelle Ollama pour qu'il continue son raisonnement avec ce
nouveau contexte -- un vrai aller-retour multi-tours, pas un seul appel.
Un garde-fou (_MAX_TURNS) empêche une boucle infinie si le modèle
n'arrive jamais à une décision finale.
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

# Garde-fou anti-boucle-infinie : nombre maximum d'allers-retours avec
# Ollama pour un seul /plan. Au-delà, on finalise avec ce qu'on a, plutôt
# que de laisser l'agent tourner indéfiniment (voir palier 4, "quelque
# chose qui empêche l'agent de tourner à l'infini").
_MAX_TURNS = 4

# Tools en LECTURE SEULE, sans aucun effet de bord, que le planificateur
# exécute lui-même automatiquement pendant la boucle (contrairement aux
# tools d'action, jamais exécutés ici -- voir executor.py). Distinct de
# la notion d'autorisation (ALLOWED_TOOLS) : ces tools sont toujours
# exécutables pendant la planification, peu importe ALLOWED_TOOLS,
# puisqu'ils ne produisent aucun effet de bord réel.
_EXPLORATORY_TOOLS = {"list_teams"}

_BASE_SYSTEM_PROMPT = (
    "Tu es un agent qui prépare l'arrivée de nouveaux collaborateurs.\n\n"
    "Tu as accès à un outil de consultation en lecture seule (list_teams) "
    "qui te permet de vérifier les équipes valides AVANT de proposer une "
    "action -- utilise-le si tu as un doute sur le nom exact d'une équipe "
    "mentionnée, plutôt que de deviner.\n\n"
    "Deux cas selon la formulation de la demande :\n"
    "1. Si l'utilisateur exprime une intention GÉNÉRALE sans lister "
    "d'actions précises (ex: \"prépare l'arrivée de X\"), propose TOUTES "
    "les actions pertinentes que tu juges nécessaires en appelant les "
    "outils disponibles -- une intention d'onboarding implique souvent "
    "plusieurs actions à la fois.\n"
    "2. Si l'utilisateur LISTE EXPLICITEMENT les actions demandées (verbes "
    "d'action précis comme \"crée X\", \"envoie Y\", \"génère Z\"), "
    "limite-toi STRICTEMENT à cette liste. N'ajoute AUCUNE action "
    "supplémentaire que l'utilisateur n'a pas mentionnée, même si elle te "
    "semble généralement utile pour un onboarding.\n\n"
    "Tu ne dois JAMAIS exécuter d'action à effet de bord toi-même : tu "
    "proposes uniquement un plan, qui sera validé par un humain avant "
    "toute exécution. Consulter list_teams n'est pas une exécution, c'est "
    "de la simple lecture.\n\n"
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

    permissions = json.loads(resource_result[0].text)

    return tools, permissions


def _build_system_prompt() -> str:
    return _BASE_SYSTEM_PROMPT + (
        f"\n\nNous sommes le {date.today().isoformat()}. "
        "Quand une date est relative (\"lundi prochain\", \"dans 2 semaines\"), "
        "calcule la date exacte au format YYYY-MM-DD avant d'appeler un outil."
    )


async def build_plan(prompt: str) -> tuple[list[dict], list[dict], str | None]:
    """Retourne (actions, excluded_actions, notice).

    Boucle multi-tours (palier 4) : si le modèle appelle un tool
    exploratoire (lecture seule, _EXPLORATORY_TOOLS), on l'exécute nous-
    mêmes immédiatement, on renvoie le résultat au modèle, et on continue
    la conversation -- jusqu'à _MAX_TURNS allers-retours maximum.

    - actions : outils autorisés que le modèle a choisi d'appeler.
    - excluded_actions : outils NON autorisés que le modèle aurait appelés
      si rien ne l'en empêchait -- même format que actions, plus une note
      expliquant pourquoi ce n'est pas exécutable actuellement.
    - notice : texte du modèle quand ni l'un ni l'autre n'a été produit
      (ex: demande hors-scope, aucun outil pertinent du tout)."""
    async with Client(_MCP_ENDPOINT) as mcp_client:
        tools = await mcp_client.list_tools()
        resource_result = await mcp_client.read_resource("config://allowed-tools")
        permissions = json.loads(resource_result[0].text)

        functional_tools = {t.name: t for t in tools if t.name not in _INTERNAL_ONLY_TOOLS}
        allowed_names = set(permissions["allowed"]) & functional_tools.keys()
        ollama_tools = [_to_ollama_tool(t) for t in functional_tools.values()]

        messages = [
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": prompt},
        ]

        data = None
        async with httpx.AsyncClient(timeout=110) as client:
            for turn in range(_MAX_TURNS):
                r = await client.post(
                    f"{OLLAMA_API_BASE}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": messages,
                        "tools": ollama_tools,
                        "think": False,
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                )
                r.raise_for_status()
                data = r.json()

                assistant_message = data.get("message", {})
                tool_calls = assistant_message.get("tool_calls", [])

                exploratory_calls = [
                    c for c in tool_calls
                    if c["function"]["name"] in _EXPLORATORY_TOOLS
                ]

                if not exploratory_calls:
                    # Rien à explorer de plus : soit une réponse finale en
                    # texte, soit des tool_calls d'action -> on sort de la
                    # boucle et on finalise ci-dessous.
                    break

                # Un ou plusieurs tools exploratoires ont été appelés :
                # on les exécute réellement (lecture seule, sans risque),
                # on renvoie le résultat au modèle, et on reboucle.
                messages.append(assistant_message)
                for call in exploratory_calls:
                    fn = call["function"]
                    result = await mcp_client.call_tool(fn["name"], fn.get("arguments", {}))
                    messages.append({
                        "role": "tool",
                        "tool_name": fn["name"],
                        "content": json.dumps(result.data),
                    })
                # Tour suivant : le modèle reprend avec ce nouveau contexte.

    tool_calls = data.get("message", {}).get("tool_calls", []) if data else []

    actions = []
    excluded_actions = []
    for call in tool_calls:
        fn = call["function"]
        tool_name = fn["name"]
        if tool_name in _EXPLORATORY_TOOLS:
            # Ne devrait plus arriver ici (déjà traité dans la boucle),
            # sécurité si _MAX_TURNS est atteint en plein milieu.
            continue
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
        notice = data.get("message", {}).get("content") or None if data else None

    return actions, excluded_actions, notice
