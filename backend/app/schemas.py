"""
Pydantic schemas: request/response models exposed by the FastAPI endpoints.

Kept separate from the SQLAlchemy models in models.py on purpose: schemas
describe the HTTP contract (what a client sends/receives), models describe
the DB table structure. This lets each evolve independently — for instance
we don't expose every DB column over HTTP, and PATCH /actions/{id} only
accepts a narrow subset of what Action.status can actually hold.

Employee has no schema yet: no endpoint reads or writes it directly (it's
populated as a side effect of tool execution). Add EmployeeRead when/if an
endpoint needs it.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

# --- Action -----------------------------------------------------------

# Mirrors the status comment on models.Action — kept in sync manually since
# Pydantic and SQLAlchemy don't share a single enum source in this project.
# "error" was added after reviewing the Agent AI side of the contract: a
# tool call can genuinely fail at execution time (network issue, invalid
# params, mcp-server down), and that needs a status distinct from
# "executed" -- it must NOT be treated as "already done" by the
# idempotency filter in routers/plans.py.
ActionStatus = Literal["proposed", "approved", "refused", "executed", "undone", "error"]


class ActionRead(BaseModel):
    """An action as returned to the client (one checklist item in the UI)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    tool: str
    params: dict[str, Any]
    summary: str
    status: ActionStatus
    idempotency_key: str
    result: Optional[dict[str, Any]] = None
    created_at: datetime
    executed_at: Optional[datetime] = None
    undone_at: Optional[datetime] = None


class ActionUpdateRequest(BaseModel):
    """Body of PATCH /actions/{id} — the human's decision on a proposed action."""

    status: Literal["approved", "refused"]
    # Only these two transitions go through this endpoint: a human approves
    # or refuses a proposed action. "executed" and "undone" are only ever
    # set by the backend itself (POST /plans/{id}/execute, POST
    # /actions/{id}/undo) — never directly by the client.


# --- Plan ---------------------------------------------------------------

PlanStatus = Literal["in_progress", "completed"]


class PlanCreateRequest(BaseModel):
    """Body of POST /plans — the free-text prompt entered by the user."""

    prompt: str


class PlanRead(BaseModel):
    """A plan with its actions, returned on creation and on lookup."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    prompt: str
    status: PlanStatus
    created_at: datetime
    actions: list[ActionRead] = []


# --- Execution / undo ----------------------------------------------------


class ExecuteResult(BaseModel):
    """One entry in the response of POST /plans/{id}/execute — one per
    approved action submitted for execution."""

    action_id: str
    status: ActionStatus
    result: Optional[dict[str, Any]] = None
    note: Optional[str] = None
    # e.g. "already executed, not replayed" when the idempotency filter
    # skips an action instead of sending it to the agent again.


class UndoResult(BaseModel):
    """Response of POST /actions/{id}/undo."""

    action_id: str
    status: ActionStatus
    note: Optional[str] = None


# --- Audit --------------------------------------------------------------


class AuditLogRead(BaseModel):
    """One row of GET /audit."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    status: ActionStatus
    note: Optional[str] = None
    timestamp: datetime
