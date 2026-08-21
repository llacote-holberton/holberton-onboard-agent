"""
Integration tests for the /plans endpoints.

agent_client.plan() and agent_client.execute() are mocked here on purpose:
these tests verify the backend's OWN orchestration logic (persistence,
status transitions, idempotency filtering, audit trail) -- not the real
Agent AI integration, whose contract is still an unconfirmed assumption
(see services/agent_client.py). Once that contract is confirmed with Hugo,
only agent_client.py should need to change; these tests mock at the
function boundary, not at the HTTP level, so they should keep passing.
"""

from unittest.mock import AsyncMock

import httpx

from app.models import Action, Plan


def test_create_plan_returns_502_when_agent_ai_is_unreachable(client, db_session, monkeypatch):
    """Reproduces the real bug reported after wiring the Streamlit frontend
    to the real stack: the Agent AI didn't have /plan yet, agent_client.plan()
    raised an httpx error, and the endpoint used to leak that as an opaque
    500. It must come back as a clean 502 with a message pointing at the
    Agent AI call, not a generic Internal Server Error."""
    monkeypatch.setattr(
        "app.services.agent_client.plan",
        AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
    )

    response = client.post("/plans", json={"prompt": "onboard Jane Doe"})

    assert response.status_code == 502
    assert "Agent AI" in response.json()["detail"]
    assert db_session.query(Plan).count() == 0  # nothing persisted on failure


def test_create_plan_persists_proposed_actions(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_client.plan",
        AsyncMock(
            return_value={
                "actions": [
                    {
                        "tool": "create_onboarding_issue",
                        "params": {"employee": "Jane Doe"},
                        "summary": "Create the onboarding issue for Jane Doe",
                    }
                ],
                "excluded_actions": [],
                "clarification": None,
                "trace": [],
            }
        ),
    )

    response = client.post("/plans", json={"prompt": "onboard Jane Doe"})

    assert response.status_code == 201
    body = response.json()
    assert body["prompt"] == "onboard Jane Doe"
    assert body["status"] == "in_progress"
    assert len(body["actions"]) == 1
    assert body["actions"][0]["status"] == "proposed"
    assert body["actions"][0]["tool"] == "create_onboarding_issue"

    # Persisted for real, not just echoed back in the response.
    assert db_session.query(Plan).count() == 1
    assert db_session.query(Action).count() == 1


def test_get_plan_404_when_missing(client):
    response = client.get("/plans/does-not-exist")

    assert response.status_code == 404


def test_execute_accepts_a_bare_string_result(client, db_session, monkeypatch):
    """Regression guard: domain_types.py's *Ref types (IssueRef, MessageRef,
    ...) are plain `str` aliases, not dicts -- e.g. mailbox.py's
    send_welcome_message returns a Message-ID string. ExecuteResult.result
    used to be typed dict-only, which would 500 on exactly this shape."""
    plan = Plan(prompt="onboard Jane Doe")
    action = Action(
        tool="send_welcome_message",
        params={"employee_name": "Jane Doe", "team": "Backend", "channel": "team"},
        summary="Send the welcome e-mail to the Backend team",
        idempotency_key="key-1",
        status="approved",
    )
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.agent_client.execute",
        AsyncMock(return_value=[{"action_id": action.id, "status": "executed", "result": "<msg-id@example>"}]),
    )

    response = client.post(f"/plans/{plan.id}/execute")

    assert response.status_code == 200
    assert response.json()[0]["result"] == "<msg-id@example>"


def test_execute_dispatches_approved_actions_and_completes_plan(client, db_session, monkeypatch):
    plan = Plan(prompt="onboard Jane Doe")
    action = Action(
        tool="create_onboarding_issue",
        params={"employee": "Jane Doe"},
        summary="Create the onboarding issue",
        idempotency_key="key-1",
        status="approved",
    )
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()

    execute_mock = AsyncMock(
        return_value=[{"action_id": action.id, "status": "executed", "result": {"issue_id": "ISSUE-1"}}]
    )
    monkeypatch.setattr("app.services.agent_client.execute", execute_mock)

    response = client.post(f"/plans/{plan.id}/execute")

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["status"] == "executed"
    assert results[0]["result"] == {"issue_id": "ISSUE-1"}
    execute_mock.assert_awaited_once()

    db_session.refresh(action)
    db_session.refresh(plan)
    assert action.status == "executed"
    assert plan.status == "completed"


def test_execute_records_error_status_when_agent_reports_a_failure(client, db_session, monkeypatch):
    """A tool call can genuinely fail (network issue, invalid params,
    mcp-server down). The agent reports status="error" for that action, and
    it must be stored as-is -- NOT silently coerced to "executed", which
    would make the idempotency filter treat a failed attempt as done."""
    plan = Plan(prompt="onboard Jane Doe")
    action = Action(
        tool="create_onboarding_issue",
        params={"employee": "Jane Doe"},
        summary="Create the onboarding issue",
        idempotency_key="key-1",
        status="approved",
    )
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()

    execute_mock = AsyncMock(
        return_value=[
            {"action_id": action.id, "status": "error", "result": None, "note": "tracker API timed out"}
        ]
    )
    monkeypatch.setattr("app.services.agent_client.execute", execute_mock)

    response = client.post(f"/plans/{plan.id}/execute")

    assert response.status_code == 200
    results = response.json()
    assert results[0]["status"] == "error"
    assert results[0]["note"] == "tracker API timed out"

    db_session.refresh(action)
    assert action.status == "error"


def test_execute_skips_action_already_executed_under_another_plan(client, db_session, monkeypatch):
    """The core idempotency guarantee: resubmitting the same intent creates
    a new Plan/Action, but if an action with the same idempotency_key was
    already executed under an earlier plan, it must NOT be dispatched to
    the agent again."""
    older_plan = Plan(prompt="onboard Jane Doe")
    already_executed = Action(
        tool="create_onboarding_issue",
        params={"employee": "Jane Doe"},
        summary="Create the onboarding issue",
        idempotency_key="shared-key",
        status="executed",
        result={"issue_id": "ISSUE-1"},
    )
    older_plan.actions.append(already_executed)

    newer_plan = Plan(prompt="onboard Jane Doe (regenerated)")
    duplicate = Action(
        tool="create_onboarding_issue",
        params={"employee": "Jane Doe"},
        summary="Create the onboarding issue",
        idempotency_key="shared-key",
        status="approved",
    )
    newer_plan.actions.append(duplicate)

    db_session.add_all([older_plan, newer_plan])
    db_session.commit()

    execute_mock = AsyncMock()
    monkeypatch.setattr("app.services.agent_client.execute", execute_mock)

    response = client.post(f"/plans/{newer_plan.id}/execute")

    assert response.status_code == 200
    results = response.json()
    assert results[0]["status"] == "executed"
    assert results[0]["note"] == "already executed under a previous plan, not replayed"
    execute_mock.assert_not_awaited()  # the whole point: the agent is never called for a duplicate
