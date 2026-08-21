"""
Unit tests for planner.py's tool-discovery filtering.

RECONCILIATION (2026-08-20): `_to_ollama_tools` (plural -- filtered AND
converted a whole list in one pure function) doesn't exist anymore after
merging dev_laurent with Hugo's Feature/palier3: the "allowed tools" design
needs the internal-tool filter and the per-tool conversion as two separate
steps (`_build_prompt_context` converts ALL functional tools, allowed or
not, then sorts by name afterwards -- see planner.py's module docstring).
The split is actually more testable than before, not less: `_functional_tools`
(the security-relevant half -- internal tools must never reach Ollama) and
`_to_ollama_tool` (pure shape conversion, singular now) are each exercised
on their own below, instead of only together.

Confirmed running locally (Laurent) -- planner.py itself still needs a
real `fastmcp` install to *import* (`from fastmcp import Client`), so this
file relies on requirements-dev.txt providing it; nothing here talks to a
real MCP server.
"""

from types import SimpleNamespace

import planner


def _fake_tool(name: str, description: str = "desc", schema: dict | None = None):
    return SimpleNamespace(name=name, description=description, inputSchema=schema or {"type": "object"})


def test_to_ollama_tool_converts_shape():
    tool = _fake_tool("create_onboarding_issue", "Crée un ticket", {"type": "object", "properties": {}})

    result = planner._to_ollama_tool(tool)

    assert result == {
        "type": "function",
        "function": {
            "name": "create_onboarding_issue",
            "description": "Crée un ticket",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_to_ollama_tool_defaults_missing_description_to_empty_string():
    tool = _fake_tool("create_onboarding_issue", description=None)

    result = planner._to_ollama_tool(tool)

    assert result["function"]["description"] == ""


def test_functional_tools_excludes_undo_compensation_tools():
    """The core guarantee this test protects: the LLM must never see (let
    alone be able to choose) a compensation/undo tool during planning --
    see docs/TOOLS.md "Outils internes (non exposés au LLM)" and
    backend/app/services/mcp_client.py, which is the only caller allowed to
    invoke them. Unlike before the reconciliation, this now holds
    regardless of ALLOWED_TOOLS -- _functional_tools() runs before the
    allowed/excluded split, so an internal tool can never leak through
    either as an `action` or as an `excluded_action`."""
    tools = [
        _fake_tool("create_onboarding_issue"),
        _fake_tool("close_onboarding_issue"),
        _fake_tool("create_employee_record"),
        _fake_tool("delete_employee_record"),
    ]

    result = planner._functional_tools(tools)

    assert set(result.keys()) == {"create_onboarding_issue", "create_employee_record"}


def test_functional_tools_returns_empty_dict_when_only_internal_tools_exist():
    tools = [_fake_tool("close_onboarding_issue"), _fake_tool("delete_employee_record")]

    result = planner._functional_tools(tools)

    assert result == {}


# --- _build_prompt_context / build_plan: allowed vs. excluded split ------
#
# New with the reconciliation: Hugo's "allowed tools" mechanism. Async, so
# uses the same pytest.mark.anyio + anyio_backend pattern already
# established in mcp_server/tests/test_tracker.py -- no real mcp-server or
# Ollama involved, both external calls are monkeypatched.

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_build_prompt_context_offers_all_functional_tools_to_ollama(monkeypatch):
    """Central design point of this mechanism (see planner.py's module
    docstring): the model is given ALL functional tools as technically
    callable, not just the allowed ones -- the allowed/excluded split
    happens after the fact in build_plan(), not by hiding tools here."""
    tools = [_fake_tool("create_onboarding_issue"), _fake_tool("create_employee_record")]
    permissions = {"allowed": ["create_onboarding_issue"], "registered_but_not_allowed": ["create_employee_record"]}

    async def fake_discover():
        return tools, permissions

    monkeypatch.setattr(planner, "_discover_tool_permissions", fake_discover)

    ollama_tools, system_prompt, allowed_names = await planner._build_prompt_context("un prompt")

    exposed_names = {t["function"]["name"] for t in ollama_tools}
    assert exposed_names == {"create_onboarding_issue", "create_employee_record"}
    assert allowed_names == {"create_onboarding_issue"}


async def test_build_plan_sorts_allowed_calls_into_actions(monkeypatch):
    """Repro (2026-08-20, Laurent) : avec la boucle "une action à la fois
    + relance" (palier 4, commit final de Hugo), un mock qui renvoie
    inconditionnellement le même tool_call à CHAQUE tour fait tourner la
    boucle jusqu'à _MAX_TURNS et collecte la même action en double à
    chaque relance (6 fois avec _MAX_TURNS=6) -- ce n'est pas un bug de
    build_plan(), c'est que le mock ne simule pas un modèle qui finit par
    répondre "Terminé" après _NUDGE. Le mock doit donc renvoyer le
    tool_call une seule fois (1er appel), puis simuler la fin de la
    boucle (tool_calls vide) sur les relances suivantes, comme le ferait
    un vrai modèle qui n'a plus rien à ajouter."""
    async def fake_context(prompt):
        return [], "system prompt", {"create_onboarding_issue"}

    call_count = {"n": 0}

    async def fake_post(self, url, json):
        call_count["n"] += 1

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if call_count["n"] == 1:
                    return {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "create_onboarding_issue", "arguments": {"employee_name": "Camille"}}},
                            ]
                        }
                    }
                return {"message": {"content": "Terminé", "tool_calls": []}}

        return FakeResponse()

    monkeypatch.setattr(planner, "_build_prompt_context", fake_context)
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    actions, excluded_actions, notice = await planner.build_plan("un prompt")

    assert len(actions) == 1
    assert actions[0]["tool"] == "create_onboarding_issue"
    assert excluded_actions == []
    assert notice is None


async def test_build_plan_sorts_blocked_calls_into_excluded_actions_with_a_note(monkeypatch):
    """The core guarantee of this whole mechanism: a call to a tool NOT in
    `allowed_names` must never land in `actions` (which the backend goes on
    to actually execute) -- it must be quarantined in `excluded_actions`
    with a human-readable note instead.

    Mock à deux temps -- voir la note dans test_build_plan_sorts_allowed_
    calls_into_actions ci-dessus : nécessaire depuis la boucle "une action
    à la fois + relance" du palier 4."""
    async def fake_context(prompt):
        return [], "system prompt", {"create_onboarding_issue"}  # create_employee_record NOT allowed

    call_count = {"n": 0}

    async def fake_post(self, url, json):
        call_count["n"] += 1

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if call_count["n"] == 1:
                    return {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "create_employee_record", "arguments": {"name": "Camille"}}},
                            ]
                        }
                    }
                return {"message": {"content": "Terminé", "tool_calls": []}}

        return FakeResponse()

    monkeypatch.setattr(planner, "_build_prompt_context", fake_context)
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    actions, excluded_actions, notice = await planner.build_plan("un prompt")

    assert actions == []
    assert len(excluded_actions) == 1
    assert excluded_actions[0]["tool"] == "create_employee_record"
    assert excluded_actions[0]["note"]
    assert notice is None


async def test_build_plan_returns_notice_when_no_tool_call_at_all(monkeypatch):
    async def fake_context(prompt):
        return [], "system prompt", set()

    async def fake_post(self, url, json):
        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"tool_calls": [], "content": "Cette demande ne concerne pas l'onboarding."}}

        return FakeResponse()

    monkeypatch.setattr(planner, "_build_prompt_context", fake_context)
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    actions, excluded_actions, notice = await planner.build_plan("un prompt hors-sujet")

    assert actions == []
    assert excluded_actions == []
    assert notice == "Cette demande ne concerne pas l'onboarding."


async def test_build_plan_retries_once_when_model_narrates_instead_of_calling_a_tool(monkeypatch):
    """RECONCILIATION 2026-08-20 (Laurent) -- voir docstring de module,
    section "narration sans tool_call". Repro réelle (session de debug
    avec Hugo, confirmée par les print() de debug côté planner.py) : au
    tout premier tour, le modèle décrit son plan en prose au lieu
    d'appeler un tool -- avant ce correctif, build_plan() concluait
    immédiatement avec ce texte comme `notice`, sans jamais donner au
    modèle la chance (pourtant promise par le system prompt) de vraiment
    appeler l'outil. Ce test verrouille la relance unique :
    narration (tour 1, aucun tool_call) -> relance -> le modèle appelle
    bien le tool au tour 2 -> action collectée normalement."""
    async def fake_context(prompt):
        return [], "system prompt", {"create_onboarding_issue"}

    call_count = {"n": 0}

    async def fake_post(self, url, json):
        call_count["n"] += 1

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                if call_count["n"] == 1:
                    return {
                        "message": {
                            "tool_calls": [],
                            "content": (
                                "Voici les actions pertinentes que je propose : "
                                "1. Créer le ticket onboarding. "
                                "Je vais maintenant proposer les outils correspondants."
                            ),
                        }
                    }
                if call_count["n"] == 2:
                    return {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "create_onboarding_issue", "arguments": {"employee_name": "Adam"}}},
                            ]
                        }
                    }
                return {"message": {"content": "Terminé", "tool_calls": []}}

        return FakeResponse()

    monkeypatch.setattr(planner, "_build_prompt_context", fake_context)
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    actions, excluded_actions, notice = await planner.build_plan("un prompt")

    assert call_count["n"] == 3  # narration + relance -> tool_call + conclusion "Terminé"
    assert len(actions) == 1
    assert actions[0]["tool"] == "create_onboarding_issue"
    assert excluded_actions == []
    assert notice is None


async def test_build_plan_only_retries_narration_once(monkeypatch):
    """La relance de narration (voir test ci-dessus) ne doit se déclencher
    QU'au tout premier tour -- un modèle qui narre encore après la relance
    doit conclure normalement, pas repartir pour un tour supplémentaire
    (sinon un vrai refus hors-sujet consommerait deux tours pour rien à
    chaque appel, voire plus si la garde `turn == 0` n'était pas
    respectée)."""
    async def fake_context(prompt):
        return [], "system prompt", set()

    call_count = {"n": 0}

    async def fake_post(self, url, json):
        call_count["n"] += 1

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"tool_calls": [], "content": f"Toujours pas de tool_call (appel {call_count['n']})."}}

        return FakeResponse()

    monkeypatch.setattr(planner, "_build_prompt_context", fake_context)
    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    actions, excluded_actions, notice = await planner.build_plan("un prompt hors-sujet")

    assert call_count["n"] == 2  # 1 relance seulement, pas plus
    assert actions == []
    assert excluded_actions == []
    assert notice == "Toujours pas de tool_call (appel 2)."


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
    assert "team non fourni" in summary


def test_summarize_names_the_missing_field_when_several_are_absent():
    """Retour de Laurent (2026-08-20, test réel) : la première version du
    placeholder générique ("(non fourni...)") ne dit pas QUEL champ manque
    -- deux champs manquants sur la même ligne de résumé affichaient le
    même texte deux fois, impossible à distinguer sans deviner. Le nom du
    champ doit apparaître dans le texte."""
    summary = planner._summarize(
        "create_employee_record",
        {"role": "Développeuse Backend"},
    )
    assert "name non fourni" in summary
    assert "team non fourni" in summary


# --- _summarize: known param aliases (e.g. employee_name -> name) --------
#
# Repro réelle (2026-08-20, même test que ci-dessus) : le LLM a appelé
# create_employee_record avec `employee_name` (accepté à l'exécution grâce
# à AliasChoices("name", "employee_name") côté employee_db.py) mais le
# résumé affichait "name non fourni" -- l'info était bien là, juste sous
# une autre clé que _summarize ne connaissait pas encore. Ces tests
# verrouillent le correctif (_PARAM_ALIASES / _resolve_known_aliases).


def test_summarize_resolves_employee_name_alias_to_name():
    summary = planner._summarize(
        "create_employee_record",
        {"employee_name": "Camille", "role": "Développeuse Backend", "team": "Backend"},
    )
    assert "Camille" in summary
    assert "non fourni" not in summary


def test_summarize_prefers_canonical_name_over_alias_if_both_provided():
    """Cas limite improbable (le LLM ne devrait jamais fournir les deux),
    mais le comportement doit rester défini : la clé canonique gagne,
    cohérent avec ce que ferait Pydantic côté mcp-server si les deux étaient
    réellement passées à l'exécution."""
    summary = planner._summarize(
        "create_employee_record",
        {
            "name": "Camille",
            "employee_name": "Ignoré",
            "role": "Développeuse Backend",
            "team": "Backend",
        },
    )
    assert "Camille" in summary
    assert "Ignoré" not in summary


def test_summarize_does_not_resolve_aliases_for_other_tools():
    """_PARAM_ALIASES est scopé par tool -- pas d'effet de bord sur un tool
    qui n'a pas ce genre d'alias déclaré côté mcp-server."""
    summary = planner._summarize(
        "create_onboarding_issue",
        {"employee_name": "Camille", "start_date": "2026-08-24"},
    )
    assert "Camille" in summary


def test_internal_only_tools_set_matches_the_undo_dispatch_table():
    """Cross-check against backend/app/services/mcp_client.py's
    _UNDO_SPEC_BY_ACTION_TOOL would be the more direct guard, but that
    module lives in a different service (different Python path, different
    deps -- fastapi/sqlalchemy aren't installed here) and importing it from
    agent's test suite would be an odd cross-service coupling. This at
    least locks in the two names that must stay in sync by hand across
    both files as of tonight's undo implementation."""
    assert planner._INTERNAL_ONLY_TOOLS == {"close_onboarding_issue", "delete_employee_record"}
