from fastapi import FastAPI
from pydantic import BaseModel
import httpx
import os
import logging

import planner
import executor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent")

app = FastAPI(title="Agent onboarding")

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")


@app.on_event("startup")
async def warmup_model():
    """Charge le modèle en mémoire dès le démarrage du conteneur, pas au
    premier clic utilisateur -- évite un timeout surprise en pleine démo
    si Ollama a déchargé le modèle après une période d'inactivité
    (OLLAMA_KEEP_ALIVE). Non bloquant : si Ollama n'est pas encore prêt,
    on log et on retentera naturellement au premier vrai appel."""
    try:
        logger.info("Réchauffement du modèle %s...", OLLAMA_MODEL)
        async with httpx.AsyncClient(timeout=180) as client:
            await client.post(f"{OLLAMA_API_BASE}/api/generate", json={
                "model": OLLAMA_MODEL,
                "prompt": "Bonjour",
                "think": False,
                "stream": False,
            })
        logger.info("Modèle %s chargé et prêt.", OLLAMA_MODEL)
    except Exception as exc:
        logger.warning("Échec du réchauffement du modèle (non bloquant) : %s", exc)


@app.get("/ping-llm")
async def ping_llm():
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{OLLAMA_API_BASE}/api/generate", json={
            "model": OLLAMA_MODEL,
            "prompt": "Réponds en une phrase : que fais-tu ?",
            "stream": False
        })
        return r.json()


@app.get("/ping")
async def ping():
    return {"status": "agent alive"}


@app.get("/tools/permissions")
async def tools_permissions():
    """Expose la resource MCP "config://allowed-tools" pour le panneau
    lecture-seule du frontend (via un proxy backend, voir ARCHITECTURE.md :
    le frontend ne parle jamais directement à l'agent)."""
    _, permissions = await planner._discover_tool_permissions()
    return permissions


class PlanRequest(BaseModel):
    prompt: str


@app.post("/plan")
async def plan(body: PlanRequest):
    actions, excluded_actions, notice, trace = await planner.build_plan(body.prompt)
    return {
        "actions": actions,
        "excluded_actions": excluded_actions,
        "clarification": notice,
        "trace": trace,
    }


class ExecuteRequest(BaseModel):
    actions: list[dict]


@app.post("/execute")
async def execute(body: ExecuteRequest):
    results = await executor.execute_actions(body.actions)
    return {"results": results}
