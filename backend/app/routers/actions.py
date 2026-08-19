"""
Endpoints for actions: the human's approve/refuse decision, and
cancellation (undo).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Action
from app.schemas import ActionRead, ActionUpdateRequest, UndoResult
from app.services import mcp_client
from app.services.audit import log_action_status

router = APIRouter(tags=["actions"])


@router.patch("/actions/{action_id}", response_model=ActionRead)
def update_action(action_id: str, body: ActionUpdateRequest, db: Session = Depends(get_db)):
    """The human's decision on a proposed action -- approve or refuse. Only
    a "proposed" action can be decided on through this endpoint; an
    already-decided or already-executed action is immutable here."""
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status != "proposed":
        raise HTTPException(
            status_code=409,
            detail=f"Action is '{action.status}', only a 'proposed' action can be approved or refused",
        )

    action.status = body.status
    log_action_status(db, action.id, action.status)
    db.commit()
    db.refresh(action)
    return action


@router.post("/actions/{action_id}/undo", response_model=UndoResult)
async def undo_action(action_id: str, db: Session = Depends(get_db)):
    """Cancellation: the backend calls the MCP server directly, with no
    re-planning through the agent (see ARCHITECTURE.md "Décision
    structurante n°2"). Only an executed action can be undone."""
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.status != "executed":
        raise HTTPException(
            status_code=409,
            detail=f"Action is '{action.status}', only an 'executed' action can be undone",
        )

    outcome = await mcp_client.undo(action.tool, action.params, action.result)

    action.status = "undone"
    action.undone_at = datetime.now(timezone.utc)
    note = outcome.get("note")
    log_action_status(db, action.id, "undone", note=note)
    db.commit()

    return UndoResult(action_id=action.id, status=action.status, note=note)
