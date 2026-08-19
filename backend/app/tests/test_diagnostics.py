"""
Tests for the connectivity endpoints: GET /agent/ping (palier 2 gate, no
LLM call) and GET /agent/ping-llm (heavier, optional, exercises Ollama).
"""

from unittest.mock import AsyncMock

import httpx


def test_ping_agent_success(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_client.ping",
        AsyncMock(return_value={"status": "agent alive"}),
    )

    response = client.get("/agent/ping")

    assert response.status_code == 200
    body = response.json()
    assert body["agent_reachable"] is True
    assert body["agent_response"] == {"status": "agent alive"}


def test_ping_agent_returns_502_when_unreachable(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_client.ping",
        AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
    )

    response = client.get("/agent/ping")

    assert response.status_code == 502
    assert "Agent AI" in response.json()["detail"]


def test_ping_agent_llm_success(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_client.ping_llm",
        AsyncMock(return_value={"response": "Je réponds à un ping."}),
    )

    response = client.get("/agent/ping-llm")

    assert response.status_code == 200
    assert response.json()["agent_response"] == {"response": "Je réponds à un ping."}


def test_ping_agent_llm_returns_502_on_timeout(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_client.ping_llm",
        AsyncMock(side_effect=httpx.ReadTimeout("timed out")),
    )

    response = client.get("/agent/ping-llm")

    assert response.status_code == 502
    assert "ping-llm" in response.json()["detail"]
