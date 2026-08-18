"""
Minimal version, just to check that the container starts, listens on the
right port, and responds to the healthcheck defined in docker-compose.yml.
No DB, no routers, no call to agent/mcp-server yet — that comes in the
next steps.
"""

import os

from fastapi import FastAPI

app = FastAPI(title="Onboarding Agent — Backend")


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
