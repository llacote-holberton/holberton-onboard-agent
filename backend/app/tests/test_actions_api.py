"""
Integration tests for the /actions endpoints (approve/refuse, undo).

mcp_client.undo() is mocked here on purpose -- see services/mcp_client.py's
"ASSUMPTION" note. These tests verify the backend's own status-transition
and validation logic, not the real MCP server integration.
"""

from unittest.mock import AsyncMock

from app.models import Action, Plan


def _make_action(db_session, **overrides):
    plan = Plan(prompt="onboard Jane Doe")
    # RECONCILIATION 2026-08-20 (Laurent) -- merge defaults and overrides
    # into a single dict before constructing Action(): the previous version
    # hardcoded tool=/params= as explicit kwargs *and* accepted **overrides,
    # so any test overriding either of them (e.g. constructing a
    # generate_handbook action, see test_actions_api_download.py) raised
    # "got multiple values for keyword argument". Fixed here as reusable
    # test infrastructure even though no test in *this* file exercises the
    # override yet.
    defaults = {
        "tool": "create_onboarding_issue",
        "params": {"employee": "Jane Doe"},
        "summary": "Create the onboarding issue",
        "idempotency_key": "key-1",
    }
    action = Action(**{**defaults, **overrides})
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(action)
    return action


def test_approve_a_proposed_action(client, db_session):
    action = _make_action(db_session)  # default status: "proposed"

    response = client.patch(f"/actions/{action.id}", json={"status": "approved"})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_cannot_decide_twice_on_the_same_action(client, db_session):
    action = _make_action(db_session, status="approved")

    response = client.patch(f"/actions/{action.id}", json={"status": "refused"})

    assert response.status_code == 409


def test_undo_calls_mcp_client_and_marks_action_undone(client, db_session, monkeypatch):
    action = _make_action(db_session, status="executed", result={"issue_id": "ISSUE-1"})

    undo_mock = AsyncMock(return_value={"status": "undone", "note": None})
    monkeypatch.setattr("app.services.mcp_client.undo", undo_mock)

    response = client.post(f"/actions/{action.id}/undo")

    assert response.status_code == 200
    assert response.json()["status"] == "undone"
    undo_mock.assert_awaited_once_with(
        "create_onboarding_issue", {"employee": "Jane Doe"}, {"issue_id": "ISSUE-1"}
    )


def test_cannot_undo_an_action_that_was_not_executed(client, db_session):
    action = _make_action(db_session)  # still "proposed"

    response = client.post(f"/actions/{action.id}/undo")

    assert response.status_code == 409
