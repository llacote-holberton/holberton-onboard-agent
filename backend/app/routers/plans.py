"""
Endpoints for plans: creation (planning step), lookup, and execution.
"""

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Action, Plan
from app.schemas import ExecuteResult, PlanCreateRequest, PlanRead
from app.services import agent_client
from app.services.agent_client import AgentAIError
from app.services.audit import log_action_status
from app.services.idempotency import compute_idempotency_key

router = APIRouter(tags=["plans"])


@router.post("/plans", response_model=PlanRead, status_code=201)
async def create_plan(body: PlanCreateRequest, db: Session = Depends(get_db)):
    """Planning step only: persist the prompt, ask the Agent AI for a list
    of proposed actions, persist each one as a proposed Action row. Nothing
    is executed here -- see POST /plans/{id}/execute."""
    plan = Plan(prompt=body.prompt)
    db.add(plan)

    try:
        plan_response = await agent_client.plan(body.prompt)
    except AgentAIError as exc:
        # The agent responded with its own clear, human-readable detail
        # (see agent/main.py's /plan handler) -- forward it and its status
        # code unchanged, rather than squashing it into a generic 502
        # built from the raw httpx exception (see AgentAIError's own
        # docstring for the bug this fixes: that detail used to never
        # reach the frontend at all).
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except httpx.HTTPError as exc:
        # Nothing was flushed/committed yet at this point, so there is
        # nothing to roll back -- but calling it explicitly documents the
        # intent and protects this code if that ordering ever changes.
        # This branch is for when the agent couldn't even be reached
        # (network failure) -- AgentAIError above handles the case where
        # it responded with an error status.
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Agent AI /plan call failed: {exc}") from exc

    proposed_actions = plan_response["actions"]
    plan.clarification = plan_response.get("clarification")
    plan.excluded_actions = plan_response.get("excluded_actions", [])
    plan.trace = plan_response.get("trace", [])

    for proposed in proposed_actions:
        action = Action(
            tool=proposed["tool"],
            params=proposed["params"],
            summary=proposed["summary"],
            idempotency_key=compute_idempotency_key(proposed["tool"], proposed["params"]),
        )
        plan.actions.append(action)

    db.flush()  # assign plan.id / action.id before the audit rows reference them
    for action in plan.actions:
        log_action_status(db, action.id, "proposed")

    db.commit()
    return plan


@router.get("/plans/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.post("/plans/{plan_id}/execute", response_model=list[ExecuteResult])
async def execute_plan(plan_id: str, db: Session = Depends(get_db)):
    """Execution step: for every action the human has approved, skip it if
    an identical action (same idempotency_key) was already executed under a
    previous plan; otherwise hand it to the Agent AI for mechanical dispatch
    (no new LLM decision here -- see ARCHITECTURE.md "Décision structurante
    n°2")."""
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    approved = [a for a in plan.actions if a.status == "approved"]
    results: list[ExecuteResult] = []
    to_dispatch = []

    for action in approved:
        duplicate = (
            db.query(Action)
            .filter(
                Action.idempotency_key == action.idempotency_key,
                Action.status == "executed",
                Action.id != action.id,
            )
            .first()
        )
        if duplicate is None:
            to_dispatch.append(action)
            continue

        note = "already executed under a previous plan, not replayed"
        action.status = "executed"
        action.result = duplicate.result
        action.executed_at = datetime.now(timezone.utc)
        log_action_status(db, action.id, "executed", note=note)
        results.append(ExecuteResult(action_id=action.id, status="executed", result=action.result, note=note))

    if to_dispatch:
        try:
            dispatched = await agent_client.execute(
                [{"action_id": a.id, "tool": a.tool, "params": a.params} for a in to_dispatch]
            )
        except AgentAIError as exc:
            # Same reasoning as create_plan() above: forward the agent's
            # own status/detail instead of a generic wrapper string.
            db.rollback()
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except httpx.HTTPError as exc:
            # Actions already resolved as duplicates above are rolled back
            # too -- the whole execute call fails together, the client can
            # retry once the agent is reachable.
            db.rollback()
            raise HTTPException(status_code=502, detail=f"Agent AI /execute call failed: {exc}") from exc

        outcomes_by_id = {r["action_id"]: r for r in dispatched}

        for action in to_dispatch:
            outcome = outcomes_by_id.get(action.id, {})
            action.status = outcome.get("status", "executed")
            action.result = outcome.get("result")
            action.executed_at = datetime.now(timezone.utc)
            log_action_status(db, action.id, action.status, note=outcome.get("note"))
            results.append(
                ExecuteResult(
                    action_id=action.id,
                    status=action.status,
                    result=action.result,
                    note=outcome.get("note"),
                )
            )

    if not any(a.status in ("proposed", "approved") for a in plan.actions):
        plan.status = "completed"

    db.commit()
    return results
