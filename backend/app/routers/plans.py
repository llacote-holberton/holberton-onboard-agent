"""
Endpoints for plans: creation (planning step), lookup, and execution.
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import FILE_GENERATING_TOOLS
from app.database import get_db
from app.models import Action, Plan
from app.schemas import ExecuteResult, PlanCreateRequest, PlanRead
from app.services import agent_client
from app.services.agent_client import AgentAIError
from app.services.audit import log_action_status
from app.services.idempotency import compute_idempotency_key

logger = logging.getLogger("plans")

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
        # CORRECTIF (2026-08-24, Laurent, portage de a2b16b7 depuis
        # feature/palier5) -- forward the agent's own status_code/detail
        # unchanged, rather than squashing every AgentAIError into a
        # generic 502 built from the raw exception (see AgentAIError's
        # own docstring for the bug this fixes). Must come BEFORE the
        # httpx.HTTPError branch below, since AgentAIError subclasses it
        # and would otherwise be caught there instead, silently losing
        # the real status code.
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except httpx.HTTPError as exc:
        # Nothing was flushed/committed yet at this point, so there is
        # nothing to roll back -- but calling it explicitly documents the
        # intent and protects this code if that ordering ever changes.
        # This branch is for when the agent couldn't even be reached at
        # all (network failure, connection refused, timeout) -- AgentAIError
        # above handles the case where it responded with an error status.
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Agent AI /plan call failed: {exc}") from exc

    proposed_actions = plan_response["actions"]
    plan.clarification = plan_response.get("clarification")
    plan.excluded_actions = plan_response.get("excluded_actions", [])
    # CORRECTIF (2026-08-24, Laurent, portage de db8b25a depuis
    # feature/palier5) -- trace tour-par-tour, voir app/models.py::Plan.trace.
    plan.trace = plan_response.get("trace", [])

    for proposed in proposed_actions:
        action = Action(
            tool=proposed["tool"],
            params=proposed["params"],
            summary=proposed["summary"],
            idempotency_key=compute_idempotency_key(proposed["tool"], proposed["params"]),
        )
        plan.actions.append(action)

    try:
        db.flush()  # assign plan.id / action.id before the audit rows reference them
        for action in plan.actions:
            log_action_status(db, action.id, "proposed")
        db.commit()
    except Exception as exc:
        # DURCISSEMENT (2026-08-24, Laurent) -- même trou que celui corrigé
        # sur feature/palier5 (jamais porté ici) : sans ce filet, une panne
        # cote ECRITURE EN BASE (ex: colonne manquante sur un volume SQLite
        # créé avant l'ajout de `clarification`/`excluded_actions` au
        # modèle Plan -- init_db() ne fait que create_all(), qui ne modifie
        # jamais une table déjà existante) remonte comme un 500 brut sans
        # aucun détail, alors même que l'agent avait répondu correctement.
        # Repro rapportée par Hugo (24/08) : "500 Server Error" générique,
        # pas 502/503 -- signe que ça casse ICI, après l'appel agent, pas
        # dans l'appel lui-même (voir le `except AgentAIError` explicite
        # juste au-dessus, qui gère désormais ce second cas séparément).
        db.rollback()
        logger.exception("Erreur inattendue en persistant le plan")
        raise HTTPException(
            status_code=500,
            detail=(
                "Une erreur inattendue est survenue en enregistrant le plan "
                "(pas un problème côté modèle IA). Réessayez ; si le "
                "problème persiste, contactez l'administrateur (voir les "
                "logs du service backend)."
            ),
        ) from exc

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
            # RECONCILIATION 2026-08-20 (Laurent) -- plan_id association:
            # for file-generating tools (see app.config.FILE_GENERATING_
            # TOOLS), always inject the REAL plan_id here, overwriting
            # whatever the LLM/agent may have proposed in params -- same
            # "never trust the LLM for correctness-critical values" pattern
            # already used for team validation (see agent/planner.py::
            # _flag_unknown_teams). This is what lets the generated file be
            # found again later for download (see routers/actions.py::
            # download_action_file and mcp_server/tools/documents.py /
            # event_calendar.py's plan_id-scoped storage).
            dispatched = await agent_client.execute(
                [
                    {
                        "action_id": a.id,
                        "tool": a.tool,
                        "params": (
                            {**a.params, "plan_id": plan_id}
                            if a.tool in FILE_GENERATING_TOOLS
                            else a.params
                        ),
                    }
                    for a in to_dispatch
                ]
            )
        except AgentAIError as exc:
            # Same reasoning as create_plan() above: forward the agent's
            # own status_code/detail instead of a generic wrapper string.
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
