"""
Tests for execute_plan()'s plan_id injection into file-generating tools'
params (RECONCILIATION 2026-08-20, Laurent -- plan_id association).

Split out from test_plans_api.py into its own file: these tests target
app.config.FILE_GENERATING_TOOLS and the injection logic in
routers/plans.py::execute_plan(), both introduced alongside this file --
keeping them together with the feature they cover makes the dependency
obvious (this file cannot pass on its own before that code exists), and
avoids mixing them into test_plans_api.py's pre-existing, unrelated
coverage of the execute endpoint.
"""

from unittest.mock import AsyncMock

from app.models import Action, Plan


def test_execute_injects_plan_id_into_params_for_file_generating_tools(client, db_session, monkeypatch):
    """File-generating tools (generate_handbook, create_calendar_event --
    see app.config.FILE_GENERATING_TOOLS) must always receive the REAL
    plan_id computed by the backend, never whatever value the LLM/agent
    proposed in the plan's params (same "never trust the LLM for
    correctness-critical values" pattern already used for team validation,
    see agent/planner.py::_flag_unknown_teams)."""
    plan = Plan(prompt="onboard Jane Doe")
    action = Action(
        tool="generate_handbook",
        params={"employee_name": "Jane Doe", "plan_id": "should-be-overwritten"},
        summary="Generate the onboarding handbook",
        idempotency_key="key-1",
        status="approved",
    )
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()

    execute_mock = AsyncMock(
        return_value=[
            {
                "action_id": action.id,
                "status": "executed",
                "result": "/app/data/documents/x/handbook.pdf",
            }
        ]
    )
    monkeypatch.setattr("app.services.agent_client.execute", execute_mock)

    response = client.post(f"/plans/{plan.id}/execute")

    assert response.status_code == 200
    execute_mock.assert_awaited_once()
    dispatched_payload = execute_mock.call_args.args[0]
    assert len(dispatched_payload) == 1
    assert dispatched_payload[0]["params"]["plan_id"] == plan.id


def test_execute_does_not_inject_plan_id_for_other_tools(client, db_session, monkeypatch):
    """Tools that don't generate a file must NOT get a plan_id injected into
    their params -- only app.config.FILE_GENERATING_TOOLS should ever see
    it."""
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
    dispatched_payload = execute_mock.call_args.args[0]
    assert "plan_id" not in dispatched_payload[0]["params"]
