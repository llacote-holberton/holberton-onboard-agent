"""DURCISSEMENT (2026-08-21, Laurent) -- palier "je casse", scénario 3 du
checkpoint : "je coupe le réseau (ou je vous fais mettre une fausse clé
d'API). Votre app doit le dire, pas boucler."

Ces tests exercent directement les routes FastAPI de agent/main.py (via
TestClient -- appels synchrones, pas de vrai serveur réseau, pas de vrai
appel LLM) pour verrouiller que CHAQUE mode de panne côté fournisseur LLM
(clé absente/refusée, réseau coupé, timeout) se traduit en une réponse
HTTP claire avec un `detail` explicite -- jamais en un 500 nu sans corps
JSON (ce que Starlette renvoie par défaut sur une exception non attrapée,
et que describe_error() côté frontend ne peut pas afficher proprement --
voir frontend/app.py) et jamais en une requête qui ne répond tout
simplement pas (le "boucle" du scénario 3).

Les exceptions simulées ci-dessous sont celles que LiteLLM lève
réellement (litellm.AuthenticationError, litellm.APIConnectionError,
litellm.Timeout...) -- voir LLM CONFIGURATION -- AGNOSTIQUE dans
planner.py's module docstring : depuis le passage à LiteLLM, planner.py
ne fait plus lui-même de requêtes HTTP ni de vérification de clé API à la
main, c'est LiteLLM qui lève ces exceptions normalisées quel que soit le
fournisseur réellement actif."""

import litellm
import pytest
from fastapi.testclient import TestClient

import main
import planner


@pytest.fixture
def client():
    return TestClient(main.app)


def test_plan_returns_502_with_clear_detail_when_api_key_is_rejected(client, monkeypatch):
    """Cas 'fausse clé' : LiteLLM lève AuthenticationError quel que soit
    le fournisseur (clé absente, invalide, ou révoquée)."""
    async def raise_auth_error(prompt):
        raise litellm.AuthenticationError(
            message="invalid x-api-key", llm_provider="anthropic", model="claude-sonnet-4-6"
        )

    monkeypatch.setattr(planner, "build_plan", raise_auth_error)

    response = client.post("/plan", json={"prompt": "Prépare l'arrivée de Camille"})

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "clé" in detail.lower()
    assert "LLM_MODEL_API_KEY" in detail


def test_plan_returns_503_with_clear_detail_when_network_is_cut(client, monkeypatch):
    """Cas 'réseau coupé' : LiteLLM lève APIConnectionError, tel qu'obtenu
    en coupant la connectivité réseau du conteneur agent (ou en pointant
    vers un fournisseur/hôte Ollama injoignable)."""
    async def raise_connect_error(prompt):
        raise litellm.APIConnectionError(
            message="Network is unreachable", llm_provider="anthropic", model="claude-sonnet-4-6"
        )

    monkeypatch.setattr(planner, "build_plan", raise_connect_error)

    response = client.post("/plan", json={"prompt": "Prépare l'arrivée de Camille"})

    assert response.status_code == 503
    detail = response.json()["detail"].lower()
    assert "réseau" in detail or "injoignable" in detail


def test_plan_returns_504_with_clear_detail_on_timeout(client, monkeypatch):
    async def raise_timeout(prompt):
        raise litellm.Timeout(message="timed out", model="claude-sonnet-4-6", llm_provider="anthropic")

    monkeypatch.setattr(planner, "build_plan", raise_timeout)

    response = client.post("/plan", json={"prompt": "Prépare l'arrivée de Camille"})

    assert response.status_code == 504
    assert "timeout" in response.json()["detail"].lower()


def test_plan_returns_502_with_clear_detail_on_rate_limit(client, monkeypatch):
    async def raise_rate_limit(prompt):
        raise litellm.RateLimitError(message="rate limited", model="claude-sonnet-4-6", llm_provider="anthropic")

    monkeypatch.setattr(planner, "build_plan", raise_rate_limit)

    response = client.post("/plan", json={"prompt": "Prépare l'arrivée de Camille"})

    assert response.status_code == 502
    assert "quota" in response.json()["detail"].lower() or "débit" in response.json()["detail"].lower()


def test_plan_never_lets_an_unexpected_exception_escape_unhandled(client, monkeypatch):
    """Filet de sécurité générique : même une exception totalement
    imprévue (ni litellm.*, ni reconnaissable par son nom de classe) doit
    finir en réponse HTTP avec un `detail`, jamais en 500 nu sans corps
    JSON exploitable."""
    async def raise_unexpected(prompt):
        raise ValueError("bug totalement imprévu")

    monkeypatch.setattr(planner, "build_plan", raise_unexpected)

    response = client.post("/plan", json={"prompt": "Prépare l'arrivée de Camille"})

    assert response.status_code == 500
    assert "detail" in response.json()
    assert response.json()["detail"]  # non vide


def test_execute_returns_502_with_clear_detail_when_mcp_server_unreachable(client, monkeypatch):
    """Même exigence côté exécution : si le serveur MCP est injoignable
    (réseau coupé) AVANT même de pouvoir dispatcher la moindre action,
    /execute doit le dire clairement plutôt que planter nu."""
    async def raise_connection_refused(actions):
        raise ConnectionRefusedError("Connection refused")

    monkeypatch.setattr(main.executor, "execute_actions", raise_connection_refused)

    response = client.post("/execute", json={"actions": []})

    assert response.status_code == 502
    assert "MCP" in response.json()["detail"]
