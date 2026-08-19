"""
Unit tests for planner.py's tool-discovery filtering.

Only `_to_ollama_tools` is exercised here -- the pure part of
_discover_tools() (see planner.py), extracted specifically so it doesn't
need a real mcp-server or the `fastmcp` package's actual network behavior
to test: it just maps/filters a list of already-fetched Tool-shaped
objects.

Confirmed running locally (Laurent) -- planner.py itself still needs a
real `fastmcp` install to *import* (`from fastmcp import Client`), so this
file relies on requirements-dev.txt providing it; nothing here talks to a
real MCP server.
"""

from types import SimpleNamespace

import planner


def _fake_tool(name: str, description: str = "desc", schema: dict | None = None):
    return SimpleNamespace(name=name, description=description, inputSchema=schema or {"type": "object"})


def test_to_ollama_tools_converts_shape():
    tools = [_fake_tool("create_onboarding_issue", "Crée un ticket", {"type": "object", "properties": {}})]

    result = planner._to_ollama_tools(tools)

    assert result == [
        {
            "type": "function",
            "function": {
                "name": "create_onboarding_issue",
                "description": "Crée un ticket",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_to_ollama_tools_defaults_missing_description_to_empty_string():
    tools = [_fake_tool("create_onboarding_issue", description=None)]

    result = planner._to_ollama_tools(tools)

    assert result[0]["function"]["description"] == ""


def test_to_ollama_tools_excludes_undo_compensation_tools():
    """The core guarantee this test protects: the LLM must never see (let
    alone be able to choose) a compensation/undo tool during planning --
    see docs/TOOLS.md "Outils internes (non exposés au LLM)" and
    backend/app/services/mcp_client.py, which is the only caller allowed to
    invoke them."""
    tools = [
        _fake_tool("create_onboarding_issue"),
        _fake_tool("close_onboarding_issue"),
        _fake_tool("create_employee_record"),
        _fake_tool("delete_employee_record"),
    ]

    result = planner._to_ollama_tools(tools)

    exposed_names = {t["function"]["name"] for t in result}
    assert exposed_names == {"create_onboarding_issue", "create_employee_record"}


def test_to_ollama_tools_returns_empty_list_when_only_internal_tools_exist():
    tools = [_fake_tool("close_onboarding_issue"), _fake_tool("delete_employee_record")]

    result = planner._to_ollama_tools(tools)

    assert result == []


# --- _summarize: visibility of the `team` default on create_employee_record
#
# 2026-08-20, plus tard la même session : mcp_server/tools/employee_db.py a
# ajouté un défaut pour `team` (précédemment refusé, revu pour aller vite
# et passer le palier en cours -- voir sa docstring pour l'historique
# complet). La condition posée pour que ce défaut soit acceptable : rester
# visible dans le résumé d'approbation humain. Ces tests verrouillent les
# deux moitiés de cette garantie -- {team} fait bien partie du template, ET
# une omission reste visible (pas juste silencieusement absente) plutôt que
# de compter sur le fallback générique qui, lui, ne le mentionnerait pas.


def test_summarize_create_employee_record_shows_the_team_value_when_provided():
    summary = planner._summarize(
        "create_employee_record",
        {"name": "Camille", "role": "Développeuse Backend", "team": "Backend"},
    )
    assert "Backend" in summary


def test_summarize_create_employee_record_flags_a_missing_team_explicitly():
    """Repro : le LLM omet `team` dans son tool-call -- `params` ne contient
    donc pas cette clé au moment du plan (le défaut de employee_db.py n'agit
    qu'à l'exécution, après approbation). Le résumé doit quand même signaler
    l'absence, pas la passer sous silence."""
    summary = planner._summarize(
        "create_employee_record",
        {"name": "Camille", "role": "Développeuse Backend"},
    )
    assert "non fourni" in summary


def test_internal_only_tools_set_matches_the_undo_dispatch_table():
    """Cross-check against backend/app/services/mcp_client.py's
    _UNDO_SPEC_BY_ACTION_TOOL would be the more direct guard, but that
    module lives in a different service (different Python path, different
    deps -- fastapi/sqlalchemy aren't installed here) and importing it from
    agent's test suite would be an odd cross-service coupling. This at
    least locks in the two names that must stay in sync by hand across
    both files as of tonight's undo implementation."""
    assert planner._INTERNAL_ONLY_TOOLS == {"close_onboarding_issue", "delete_employee_record"}
