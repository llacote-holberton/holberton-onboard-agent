"""
Resource MCP exposant, en lecture seule, quels tools sont autorisés pour
l'agent LLM -- distinct des tools eux-mêmes (@mcp.tool), une resource MCP
sert à exposer des données consultables, pas des actions exécutables.

Configuration : ALLOWED_TOOLS, liste de noms de fonctions séparés par des
virgules (ex: "create_onboarding_issue,send_welcome_message"). Si absente
ou vide, tous les tools enregistrés sont autorisés par défaut (compatible
avec le comportement actuel du projet, pas de restriction implicite).

Croise systématiquement la configuration avec les tools réellement
enregistrés via @mcp.tool (list_tools(), API serveur FastMCP -- même nom
que côté client mais appelée directement sur l'instance `mcp`) : un nom
présent dans ALLOWED_TOOLS mais qui ne correspond à aucun tool réellement
défini est signalé à part, jamais silencieusement ignoré ni traité comme
autorisé.
"""

import os

from mcp_instance import mcp


def _parse_allowed_tools_env() -> set[str] | None:
    """None = pas de restriction configurée (ALLOWED_TOOLS absente/vide) --
    distinct d'un set vide, qui signifierait "aucun tool autorisé"."""
    raw = os.environ.get("ALLOWED_TOOLS", "").strip()
    if not raw:
        return None
    return {name.strip() for name in raw.split(",") if name.strip()}


@mcp.resource("config://allowed-tools")
async def allowed_tools_resource() -> dict:
    """Retourne trois listes de noms de tools :
    - allowed : autorisés ET réellement enregistrés (@mcp.tool)
    - registered_but_not_allowed : enregistrés mais exclus par ALLOWED_TOOLS
    - allowed_but_not_registered : présents dans ALLOWED_TOOLS mais ne
      correspondant à aucun tool réellement défini (faute de frappe,
      tool renommé/supprimé, etc.)
    """
    registered_tools = await mcp.list_tools()  # list[Tool], API serveur FastMCP
    registered_names = {t.name for t in registered_tools}

    configured = _parse_allowed_tools_env()

    if configured is None:
        allowed = registered_names
        allowed_but_not_registered: set[str] = set()
    else:
        allowed = configured & registered_names
        allowed_but_not_registered = configured - registered_names

    return {
        "allowed": sorted(allowed),
        "registered_but_not_allowed": sorted(registered_names - allowed),
        "allowed_but_not_registered": sorted(allowed_but_not_registered),
    }
