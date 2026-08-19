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

from app.models import Action, Plan


def test_create_plan_persists_proposed_actions(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_client.plan",
        AsyncMock(
            return_value=[
                {
                    "tool": "create_onboarding_issue",
                    "params": {"employee": "Jane Doe"},
                    "summary": "Create the onboarding issue for Jane Doe",
                }
            ]
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
