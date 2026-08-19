"""
FastAPI application entrypoint.

Wires together the lifespan handler (creates DB tables on startup via
init_db(), see database.py) and the routers for plans, actions, and the
audit trail.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import actions, audit, plans


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

app.include_router(audit.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "backend", "status": "running"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BACKEND_PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
