"""
Endpoints for actions: the human's approve/refuse decision, and
cancellation (undo).
"""

import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import DATA_DIR, FILE_GENERATING_TOOLS
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

    try:
        outcome = await mcp_client.undo(action.tool, action.params, action.result)
    except Exception as exc:
        # Broad on purpose: fastmcp can raise connection errors, protocol
        # errors, or its own ToolError -- all of them mean the same thing
        # here, "the MCP server call failed", and none should surface as an
        # opaque 500.
        db.rollback()
        raise HTTPException(status_code=502, detail=f"MCP server 'undo' call failed: {exc}") from exc

    action.status = "undone"
    action.undone_at = datetime.now(timezone.utc)
    note = outcome.get("note")
    log_action_status(db, action.id, "undone", note=note)
    db.commit()

    return UndoResult(action_id=action.id, status=action.status, note=note)


@router.get("/actions/{action_id}/download")
def download_action_file(action_id: str, db: Session = Depends(get_db)):
    """RECONCILIATION 2026-08-20 (Laurent) -- lets the frontend hand the
    generated file's bytes to the end user (see mcp_server/tools/
    documents.py, event_calendar.py, and routers/plans.py::execute_plan()'s
    plan_id injection for how `action.result` ends up holding a path under
    DATA_DIR). BACKEND_URL only resolves inside the docker network, so the
    frontend must proxy these bytes server-side rather than link directly
    to this endpoint from the end user's browser -- see frontend/app.py."""
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.tool not in FILE_GENERATING_TOOLS:
        raise HTTPException(
            status_code=400, detail=f"'{action.tool}' does not generate a downloadable file."
        )
    if action.status != "executed" or not action.result:
        raise HTTPException(
            status_code=409, detail=f"Action is '{action.status}', no generated file to download yet."
        )

    path = Path(str(action.result)).resolve()
    # is_relative_to guards against a manipulated/unexpected result path
    # ever serving a file from outside DATA_DIR -- defense in depth, since
    # action.result is only ever written by our own dispatch code, but
    # cheap and worth keeping explicit.
    if not path.is_relative_to(DATA_DIR) or not path.is_file():
        raise HTTPException(status_code=404, detail="Generated file not found on disk.")

    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, filename=path.name, media_type=media_type)
