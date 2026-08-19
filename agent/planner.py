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
#
# NOTE (2026-08-20) : {team} a été ajouté au template de
# create_employee_record -- condition nécessaire pour que le nouveau défaut
# de `team` (voir mcp_server/tools/employee_db.py::_TEAM_PLACEHOLDER) reste
# acceptable : la valeur retenue (fournie par le LLM ou le placeholder de
# repli) doit rester visible ici pour qu'un humain puisse la corriger ou
# refuser l'action, plutôt que d'écrire silencieusement en base une équipe
# potentiellement fausse ou un placeholder non voulu.
_SUMMARY_TEMPLATES = {
    "create_onboarding_issue": "Créer le ticket onboarding pour {employee_name}",
    "create_employee_record": "Créer la fiche employé pour {name} ({role}) — équipe : {team}",
    "send_welcome_message": "Envoyer un message d'accueil ({channel}) à l'équipe {team} pour {employee_name}",
    "generate_handbook": "Générer le document '{template}'",
    "create_calendar_event": "Créer l'événement '{title}'",
}

# Fonctions de compensation ("undo") : outils internes appelés uniquement
# par le backend lors d'une annulation (POST /actions/{id}/undo, voir
# backend/app/services/mcp_client.py), jamais par le LLM au moment du plan
# -- voir docs/TOOLS.md "Outils internes (non exposés au LLM)". mcp-server
# ne fait pourtant aucune distinction structurelle entre un tool de
# création et un tool de compensation (les deux sont juste @mcp.tool dans
# le même fichier -- voir tools/tracker.py, tools/employee_db.py), donc
# list_tools() les renvoie tous pêle-mêle : c'est ici, pas côté
# mcp-server, que le tri se fait avant de les proposer à Ollama. Liste à
# tenir à jour à la main à chaque nouvelle fonction de compensation
# implémentée -- pas de convention de nommage (ex. préfixe "undo_") ni de
# métadonnée FastMCP exploitée pour l'instant, volontairement simple tant
# qu'il n'y a que deux entrées.
_INTERNAL_ONLY_TOOLS = {
    "close_onboarding_issue",
    "delete_employee_record",
}


# Alias de paramètre connus, par tool -- miroir de ce que chaque tool
# déclare côté mcp-server via Field(validation_alias=AliasChoices(...))
# (aujourd'hui : `name`/`employee_name` sur create_employee_record, voir
# mcp_server/tools/employee_db.py). Duplication assumée, même famille que
# _SUMMARY_TEMPLATES et _INTERNAL_ONLY_TOOLS ci-dessus : le schéma JSON que
# list_tools() renvoie n'expose QUE le nom canonique ("name"), jamais
# l'alias (confirmé -- voir mcp_server/tests/test_employee_db.py::
# test_create_employee_record_schema_does_not_expose_employee_name), donc
# _summarize n'a aucun moyen de le découvrir dynamiquement à partir du
# schéma seul. À tenir à jour à la main si un alias est ajouté ou retiré
# côté mcp-server.
#
# Repro réelle (2026-08-20) qui a révélé le besoin de cette table : le LLM
# a appelé create_employee_record avec `employee_name` (accepté sans
# problème à l'exécution grâce à l'alias) mais le résumé affichait "name
# non fourni" -- alors que l'info était bien là, juste sous une autre clé.
# Résultat trompeur pour l'humain qui approuve : ça peut faire refuser une
# action qui aurait pourtant fonctionné.
_PARAM_ALIASES = {
    "create_employee_record": {"name": ("employee_name",)},
}


def _resolve_known_aliases(tool_name: str, params: dict) -> dict:
    """Complète `params` avec la clé canonique quand seule une clé alias
    connue a été fournie, AVANT de construire le résumé -- voir
    _PARAM_ALIASES ci-dessus. Ne modifie jamais le dict original (c'est
    celui qui est aussi renvoyé tel quel dans l'Action, params bruts
    inclus -- voir build_plan)."""
    aliases = _PARAM_ALIASES.get(tool_name)
    if not aliases:
        return params
    resolved = dict(params)
    for canonical, alt_keys in aliases.items():
        if canonical not in resolved:
            for alt in alt_keys:
                if alt in resolved:
                    resolved[canonical] = resolved[alt]
                    break
    return resolved


class _MissingParamAsPlaceholder(dict):
    """Utilisé par _summarize ci-dessous : quand un champ du template n'a
    pas été fourni par le LLM au moment du plan (ex: `team` omis sur
    create_employee_record), affiche un texte explicite au lieu de faire
    échouer le format() -- voir la note 2026-08-20 juste en dessous pour
    pourquoi c'est important, pas juste cosmétique.

    Le nom du champ manquant est inclus dans le texte (pas juste "non
    fourni" générique) -- retour direct de Laurent sur la première version
    de ce message : deux champs manquants sur la même ligne de résumé
    (ex: `name` ET `team` sur create_employee_record) affichaient le même
    texte générique deux fois, impossible de savoir lequel était lequel
    sans deviner depuis la position dans la phrase."""

    def __missing__(self, key):
        return f"({key} non fourni — une valeur par défaut sera utilisée à l'exécution)"


def _summarize(tool_name: str, params: dict) -> str:
    # NOTE (2026-08-20) : `params` ici, ce sont les arguments BRUTS renvoyés
    # par le tool-call du LLM, AVANT toute validation/défaut Pydantic côté
    # mcp-server (qui n'a lieu qu'à l'exécution, après approbation humaine).
    # Donc si le LLM omet `team`, ce dict ne contient pas "team" du tout à
    # ce stade. `create_employee_record` s'appuie maintenant sur un défaut
    # pour `team` (voir mcp_server/tools/employee_db.py::_TEAM_PLACEHOLDER)
    # dont la justification explicite est : "visible dans le résumé
    # d'approbation, l'humain peut refuser si besoin". Un simple
    # `template.format(**params)` qui lève KeyError sur le champ manquant
    # et retombe sur le fallback brut ci-dessous NE MENTIONNERAIT MÊME PAS
    # `team` (le fallback ne liste que les clés présentes dans `params`) --
    # ça briserait cette garantie en silence. `_MissingParamAsPlaceholder`
    # comble spécifiquement ce trou : un champ absent du template s'affiche
    # explicitement comme tel, plutôt que de disparaître du résumé.
    #
    # `_resolve_known_aliases` doit passer AVANT : sinon un champ fourni
    # sous un alias connu (ex: `employee_name` au lieu de `name`) serait lui
    # aussi affiché comme "non fourni", ce qui serait faux -- voir
    # _PARAM_ALIASES ci-dessus pour la repro qui a motivé ce correctif.
    params_for_summary = _resolve_known_aliases(tool_name, params)
    template = _SUMMARY_TEMPLATES.get(tool_name)
    if template:
        try:
            return template.format_map(_MissingParamAsPlaceholder(params_for_summary))
        except (IndexError, ValueError):
            pass
    # Fallback si le template ne correspond plus aux vrais paramètres du
    # tool (ex: signature modifiée par un·e coéquipier·ère) -- affiche les
    # paramètres bruts plutôt qu'un nom de tool sec et peu lisible.
    if params:
        readable = ", ".join(f"{k}: {v}" for k, v in params.items())
        return f"{tool_name} ({readable})"
    return f"Exécuter {tool_name}"


def _to_ollama_tools(tools: list) -> list[dict]:
    """Convertit une liste d'objets Tool MCP (déjà en JSON Schema pour leurs
    paramètres) au format tool-calling d'Ollama, en excluant les fonctions
    de compensation internes (_INTERNAL_ONLY_TOOLS) -- le LLM ne doit
    jamais pouvoir les choisir dans un plan. Fonction pure, séparée de
    _discover_tools() ci-dessous, pour être testable sans dépendre d'un
    vrai mcp-server ni du package fastmcp."""
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
        if t.name not in _INTERNAL_ONLY_TOOLS
    ]


async def _discover_tools() -> list[dict]:
    """Lecture seule -- aucun effet de bord. Convertit le schéma MCP
    (déjà en JSON Schema) au format tool-calling d'Ollama."""
    async with Client(_MCP_ENDPOINT) as mcp_client:
        tools = await mcp_client.list_tools()

    return _to_ollama_tools(tools)


async def build_plan(prompt: str) -> list[dict]:
    tools = await _discover_tools()

    async with httpx.AsyncClient(timeout=110) as client:
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
