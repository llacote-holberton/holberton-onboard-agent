"""
SQLAlchemy models: Plan, Action, Employee, AuditLog.

Status values are plain strings on purpose, not a DB-level enum — keeps
SQLite migrations trivial for a project this size. Valid values are listed
next to each `status` column below.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Plan(Base):
    __tablename__ = "plans"

    id = Column(String, primary_key=True, default=_uuid)
    prompt = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="in_progress")
    # in_progress | completed
    created_at = Column(DateTime, default=_now)

    actions = relationship("Action", back_populates="plan", cascade="all, delete-orphan")


class Action(Base):
    __tablename__ = "actions"

    id = Column(String, primary_key=True, default=_uuid)
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)

    tool = Column(String, nullable=False)  # e.g. "create_onboarding_issue"
    params = Column(JSON, nullable=False, default=dict)
    summary = Column(String, nullable=False)  # human-readable, shown in the checklist UI

    status = Column(String, nullable=False, default="proposed")
    # proposed | approved | refused | executed | undone | error
    # "error": the agent attempted the tool call and it failed (network,
    # invalid params, mcp-server down, ...). Distinct from "executed" so
    # the idempotency filter in routers/plans.py never treats a failed
    # attempt as "already done".

    idempotency_key = Column(String, nullable=False, index=True)
    # Not unique on purpose: re-submitting the same intent creates new Action
    # rows that share the same idempotency_key as an already-executed one —
    # see ARCHITECTURE.md and SEQUENCES.md diagram 3 (execution).

    result = Column(JSON, nullable=True)  # tool output once executed, e.g. an IssueRef

    created_at = Column(DateTime, default=_now)
    executed_at = Column(DateTime, nullable=True)
    undone_at = Column(DateTime, nullable=True)

    plan = relationship("Plan", back_populates="actions")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    team = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=_uuid)
    action_id = Column(String, ForeignKey("actions.id"), nullable=False)
    status = Column(String, nullable=False)
    # proposed | approved | refused | executed | undone | error
    note = Column(String, nullable=True)  # e.g. "already executed, not replayed"
    timestamp = Column(DateTime, default=_now)

    action = relationship("Action")
