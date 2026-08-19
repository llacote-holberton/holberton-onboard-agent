"""
FastAPI application entrypoint.

Wires together the lifespan handler (creates DB tables on startup via
init_db(), see database.py) and the routers for plans, actions, and the
audit trail.
"""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from app.database import init_db
from app.routers import actions, audit, plans
from app.services import agent_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    init_db()
    yield
    # --- shutdown ---
    # Nothing to clean up explicitly here: SQLAlchemy sessions are opened
    # and closed per-request by the get_db() dependency, not held at the
    # application level.


app = FastAPI(title="Onboarding Agent — Backend", lifespan=lifespan)

app.include_router(plans.router)
app.include_router(actions.router)
app.include_router(audit.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "backend", "status": "running"}


@app.get("/agent/ping")
async def ping_agent():
    """Palier 2 gate: proves the backend can reach and talk to the Agent
    AI end to end (backend -> agent -> Ollama), with no project-specific
    planning/execution logic involved -- that comes later. See
    agent_client.ping()."""
    try:
        agent_response = await agent_client.ping()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Agent AI unreachable: {exc}") from exc
    return {"agent_reachable": True, "agent_response": agent_response}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BACKEND_PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
