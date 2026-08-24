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
    clarification = Column(Text, nullable=True)
    # Texte du modèle quand ni actions ni excluded_actions n'ont été
    # produits (ex: demande hors-scope). None sinon.
    excluded_actions = Column(JSON, nullable=False, default=list)
    # Outils NON autorisés que le modèle aurait appelés si rien ne l'en
    # empêchait -- même format que Action (tool/params/summary), plus une
    # note explicative. Voir mcp_server/resources.py, agent/planner.py.
    trace = Column(JSON, nullable=False, default=list)
    # CORRECTIF (2026-08-24, Laurent, portage de db8b25a depuis
    # feature/palier5) -- trace tour-par-tour de la planification
    # (exploration/proposal/final, + "narration" propre à dev_laurent),
    # pour le panneau "Pourquoi ce plan ?" côté frontend. Voir
    # agent/planner.py::build_plan().
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

    @property
    def tool(self) -> str:
        """Nom du tool concerne par cette ligne (ex. "create_onboarding_issue").

        Pas de colonne dediee : derive de la relation `action` existante,
        pour ne pas avoir a modifier tous les points d'ecriture de
        log_audit_event() (non vus ici -- see routers/plans.py) juste pour
        leur faire porter une info deja disponible via action_id. Cote
        lecture, from_attributes=True (Pydantic) lit les proprietes Python
        comme des attributs normaux -- voir AuditLogRead dans schemas.py.

        Limite assumee : un acces .tool par ligne declenche potentiellement
        une requete SQLAlchemy separee (lazy load de `action`) si la
        session n'a pas deja cette Action en cache -- un N+1 sans gravite
        vu le volume d'un projet de ce format, mais a garder en tete si
        /audit devient lourd un jour (solution : eager-load avec
        `joinedload(AuditLog.action)` dans la query du routeur).
        """
        return self.action.tool
