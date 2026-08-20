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

Extension "boucle d'itération" (palier 4) : deux mécanismes distincts,
tous deux basés sur la même boucle multi-tours.

1. Tools EXPLORATOIRES (_EXPLORATORY_TOOLS, ex: list_teams) : en lecture
   seule, sans effet de bord. Exécutés immédiatement par l'agent, leur
   résultat est renvoyé au modèle qui continue son raisonnement avec ce
   contexte enrichi.

2. Construction du plan par relances successives : plutôt que d'exiger
   du modèle qu'il énumère toutes les actions d'un coup en une seule
   réponse (peu fiable avec un petit modèle -- observé en pratique : il
   omet ou invente des actions au-delà de la première), on récupère les
   actions une par une. Après chaque tool_call d'action, on lui redemande
   explicitement "autre chose ?" (_NUDGE) avant de finaliser. Chaque
   proposition n'est PAS exécutée à ce stade (aucun effet de bord), juste
   accumulée -- seul un accusé de réception factice est renvoyé pour
   garder la conversation cohérente, jusqu'à ce que le modèle réponde
   qu'il n'a plus rien à ajouter.

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
# Ollama pour un seul /plan (exploration + relances de construction du
# plan confondues). Au-delà, on finalise avec ce qu'on a accumulé,
# plutôt que de laisser l'agent tourner indéfiniment.
_MAX_TURNS = 8

# Tools en LECTURE SEULE, sans aucun effet de bord, que le planificateur
# exécute lui-même automatiquement pendant la boucle (contrairement aux
# tools d'action, jamais exécutés ici -- voir executor.py). Distinct de
# la notion d'autorisation (ALLOWED_TOOLS) : ces tools sont toujours
# exécutables pendant la planification, peu importe ALLOWED_TOOLS,
# puisqu'ils ne produisent aucun effet de bord réel.
_EXPLORATORY_TOOLS = {"list_teams"}

# Relance envoyée après chaque action proposée, pour construire le plan
# progressivement plutôt que d'exiger une énumération complète en un
# seul tour (peu fiable en pratique avec un petit modèle).
_NUDGE = (
    "As-tu d'autres actions pertinentes à proposer pour compléter cette "
    "demande ? Si oui, appelle le ou les outils correspondants "
    "maintenant. Si non, ou si tu as déjà tout proposé, réponds "
    "uniquement par le mot \"Terminé\", sans appeler aucun outil."
)

_BASE_SYSTEM_PROMPT = (
    "Tu es un agent qui prépare l'arrivée de nouveaux collaborateurs.\n\n"
    "Deux cas selon la formulation de la demande :\n"
    "1. Si l'utilisateur exprime une intention GÉNÉRALE sans lister "
    "d'actions précises (ex: \"prépare l'arrivée de X\"), propose les "
    "actions pertinentes que tu juges nécessaires -- une intention "
    "d'onboarding implique souvent plusieurs actions à la fois. Tu peux "
    "les proposer une par une, on te redemandera s'il en manque.\n"
    "2. Si l'utilisateur LISTE EXPLICITEMENT les actions demandées (verbes "
    "d'action précis comme \"crée X\", \"envoie Y\", \"génère Z\"), "
    "propose un outil correspondant à chaque action listée, sans en "
    "ajouter d'autres non mentionnées.\n\n"
    "Tu ne dois JAMAIS exécuter d'action à effet de bord toi-même : tu "
    "proposes uniquement un plan, qui sera validé par un humain avant "
    "toute exécution.\n\n"
    "Vérification d'équipe : list_teams (lecture seule, à utiliser "
    "librement) retourne la liste exacte des équipes valides. Si le nom "
    "d'équipe mentionné n'est pas déjà un nom précis (ex: \"l'équipe "
    "technique\" plutôt que \"Backend\"), appelle list_teams avant toute "
    "action nécessitant une équipe -- ne devine jamais.\n\n"
    "Distingue deux types de paramètres :\n"
    "- Paramètres d'IDENTIFICATION (équipe, date, email, identifiant) : "
    "ne les invente jamais au hasard, déduis-les du contexte quand c'est "
    "raisonnable.\n"
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

    Boucle multi-tours (palier 4) combinant deux mécanismes -- voir le
    docstring du module pour le détail :
    1. Exploration en lecture seule (list_teams) avant de décider.
    2. Construction du plan par relances successives ("autre chose ?"),
       plutôt qu'une énumération complète exigée en un seul tour.

    - actions : outils autorisés que le modèle a choisi d'appeler,
      accumulés au fil des tours.
    - excluded_actions : outils NON autorisés que le modèle aurait
      appelés si rien ne l'en empêchait -- même format que actions, plus
      une note expliquant pourquoi ce n'est pas exécutable actuellement.
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

        collected_action_calls: list[dict] = []
        final_text: str | None = None

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

                print(f"[TOUR {turn + 1}] tools appelés: {[c['function']['name'] for c in tool_calls]}")

                if not tool_calls:
                    # Réponse finale en texte -- soit rien à proposer du
                    # tout (premier tour), soit "Terminé" après relance.
                    final_text = assistant_message.get("content")
                    print(f"[TOUR {turn + 1}] -> arrêt, texte final: {final_text!r}")
                    break

                messages.append(assistant_message)

                exploratory_calls = [
                    c for c in tool_calls if c["function"]["name"] in _EXPLORATORY_TOOLS
                ]
                action_calls = [
                    c for c in tool_calls if c["function"]["name"] not in _EXPLORATORY_TOOLS
                ]

                # Exploration : exécutée réellement (lecture seule, sans
                # risque), résultat renvoyé pour enrichir le contexte.
                for call in exploratory_calls:
                    fn = call["function"]
                    result = await mcp_client.call_tool(fn["name"], fn.get("arguments", {}))
                    messages.append({
                        "role": "tool",
                        "tool_name": fn["name"],
                        "content": json.dumps(result.data),
                    })

                # Actions : jamais exécutées ici (aucun effet de bord
                # pendant la planification) -- juste accumulées, avec un
                # accusé de réception factice pour garder la conversation
                # cohérente (chaque tool_call attend une réponse "tool").
                for call in action_calls:
                    fn = call["function"]
                    collected_action_calls.append(call)
                    messages.append({
                        "role": "tool",
                        "tool_name": fn["name"],
                        "content": "Proposition enregistrée pour le plan.",
                    })

                if action_calls and not exploratory_calls:
                    # Au moins une action proposée ce tour, rien à
                    # explorer en parallèle : relance CIBLÉE plutôt que
                    # générique -- énumère explicitement les tools pas
                    # encore utilisés, avec leur description. Un petit
                    # modèle répond plus fiablement à une checklist
                    # concrète qu'à un simple rappel ouvert ("autre
                    # chose ?"), qui laissait trop souvent le modèle
                    # s'arrêter avant d'avoir couvert tous les outils
                    # pertinents (repro observée : create_calendar_event
                    # régulièrement omis même quand une réunion était
                    # explicitement demandée dans un plan multi-actions).
                    used_names = {c["function"]["name"] for c in collected_action_calls}
                    remaining = {
                        name: t for name, t in functional_tools.items()
                        if name not in used_names and name not in _EXPLORATORY_TOOLS
                    }
                    if remaining:
                        remaining_list = "\n".join(
                            f"- {name} : {t.description or ''}"
                            for name, t in remaining.items()
                        )
                        nudge = (
                            "Voici les outils que tu n'as pas encore utilisés pour ce "
                            f"plan :\n{remaining_list}\n\n"
                            "Est-ce que l'un d'eux est pertinent pour compléter la "
                            "demande initiale ? Si oui, appelle-le maintenant. Si "
                            "aucun n'est pertinent, réponds uniquement par le mot "
                            "\"Terminé\", sans appeler aucun outil."
                        )
                    else:
                        nudge = _NUDGE
                    messages.append({"role": "user", "content": nudge})
                # Sinon (exploration seule, ou mélange) -> on reboucle
                # directement, le modèle reprend avec le contexte enrichi.

    actions = []
    excluded_actions = []
    for call in collected_action_calls:
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
        notice = final_text or None

    return actions, excluded_actions, notice
