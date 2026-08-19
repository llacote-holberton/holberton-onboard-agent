"""
Read-only audit trail endpoint.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Action, AuditLog
from app.schemas import AuditLogRead

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditLogRead])
def list_audit_log(
    action_id: str | None = Query(default=None, description="Filter by action id"),
    plan_id: str | None = Query(
        default=None,
        description=(
            "Filter by plan id, via a join on the action's plan_id. Lets a "
            "client fetch the full trace of one plan (proposed -> approved -> "
            "executed/error/undone, across every action and tool) in a "
            "single call instead of one /audit?action_id=... per action."
        ),
    ),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)

    if action_id is not None:
        query = query.filter(AuditLog.action_id == action_id)

    if plan_id is not None:
        # Ascending here (oldest first) rather than the default desc below:
        # a plan's trace reads as a story -- proposed, then approved, then
        # executed -- so chronological order is the natural one to display.
        # Left the unfiltered /audit (used as a general "what just happened"
        # feed) on desc/newest-first, unchanged, to avoid a silent behavior
        # change for any existing caller of the plain endpoint.
        query = query.join(Action, Action.id == AuditLog.action_id).filter(Action.plan_id == plan_id)
        query = query.order_by(AuditLog.timestamp.asc())
    else:
        query = query.order_by(AuditLog.timestamp.desc())

    return query.all()
