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

# --- Coordinated timeout chain (frontend -> backend -> agent -> Ollama) ---
# RECONCILIATION STEP 3bis (2026-08-21, Laurent) : un seul réglage,
# OLLAMA_CALL_TIMEOUT_SECONDS (voir .env.example), propage sa valeur sur
# toute la chaîne -- chaque couche englobante lit la MÊME variable
# d'environnement (voir docker-compose.yml, `environment:` de agent/
# backend/frontend) et ajoute sa propre marge en code plutôt que de
# recalculer 3 nombres séparés à la main à chaque changement de machine
# ou de modèle (exactement le genre de réglage qu'on a dû retoucher ce
# soir en passant de qwen3:0.6b à qwen3:8b). Voir agent/planner.py::
# _OLLAMA_CALL_TIMEOUT pour la couche la plus intérieure et le détail du
# schéma de marge (+15s par couche englobante directe).
#
# AGENT_PLAN_TIMEOUT_SECONDS ci-dessous est la valeur de la couche
# backend -> agent (utilisée par agent_client.py pour /plan) :
# OLLAMA_CALL_TIMEOUT_SECONDS + 15s.
OLLAMA_CALL_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_CALL_TIMEOUT_SECONDS", 110))
AGENT_PLAN_TIMEOUT_SECONDS = OLLAMA_CALL_TIMEOUT_SECONDS + 15
