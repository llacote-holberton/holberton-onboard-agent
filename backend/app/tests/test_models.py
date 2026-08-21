"""
Model-level tests -- kept separate from test_plans_api.py (which exercises
the HTTP endpoints with agent_client mocked) because this one is purely
about SQLAlchemy relationship/property behavior, no FastAPI client needed.
"""

from app.models import Action, AuditLog, Plan


def test_audit_log_tool_property_reads_through_the_action_relationship(db_session):
    """Regression guard for the "audit log doesn't say which tool" gap
    Laurent hit while debugging: GET /audit used to return action_id/status/
    note/timestamp with no way to tell which tool a line was about, short of
    cross-referencing GET /plans/{id}. AuditLog.tool is a derived property
    (not a duplicated column) so this locks in that it actually resolves
    through the `action` relationship instead of raising or returning None."""
    plan = Plan(prompt="onboard Jane Doe")
    action = Action(
        tool="create_onboarding_issue",
        params={"employee_name": "Jane Doe"},
        summary="Create the onboarding issue",
        idempotency_key="key-1",
        status="error",
    )
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()

    audit_entry = AuditLog(action_id=action.id, status="error", note="missing_argument: checklist")
    db_session.add(audit_entry)
    db_session.commit()
    db_session.refresh(audit_entry)

    assert audit_entry.tool == "create_onboarding_issue"
