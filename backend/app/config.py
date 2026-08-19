"""
Centralized configuration, read from environment variables.
The defaults below are for running locally outside Docker (e.g. pytest);
docker-compose.yml overrides each of them with the right values for the
compose network (see ARCHITECTURE.md).
"""

import os
from pathlib import Path

# --- Network ---------------------------------------------------------

BACKEND_PORT = int(os.environ.get("BACKEND_PORT", 8000))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info")

# --- Internal services called by the backend ---------------------------
# AGENT_AI_URL: plan generation + execution of approved creations.
# MCP_SERVER_URL: cancellation (undo) only, called directly.

AGENT_AI_URL = os.environ.get("AGENT_AI_URL", "http://localhost:8100")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8200")

# --- Shared storage ----------------------------------------------------
# DATA_DIR must always have the SAME value as on the mcp-server side (see
# docker-compose.yml): it's the same directory, mounted in both containers.
# The backend makes sure it exists, so SQLAlchemy can create onboarding.db
# on first startup.

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / "onboarding.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# documents/ and calendar/ are created and populated by mcp-server (not by
# the backend) — we only keep the paths here to serve already-generated
# files via the future download endpoints.
DOCUMENTS_DIR = DATA_DIR / "documents"
CALENDAR_DIR = DATA_DIR / "calendar"
