"""
Read-only audit trail endpoint.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog
from app.schemas import AuditLogRead

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditLogRead])
def list_audit_log(
    action_id: str | None = Query(default=None, description="Filter by action id"),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if action_id is not None:
        query = query.filter(AuditLog.action_id == action_id)
    return query.all()
