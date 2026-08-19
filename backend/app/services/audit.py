"""
Shared helper for writing AuditLog rows. Every status transition on an
Action goes through this single function, so the audit trail can't be
forgotten in one endpoint and not another.
"""

from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action_status(db: Session, action_id: str, status: str, note: str | None = None) -> None:
    db.add(AuditLog(action_id=action_id, status=status, note=note))
