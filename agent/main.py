from fastapi import FastAPI, HTTPException
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
    """Palier 5 -- durcissement : catch explicitement les pannes de
    dépendance (serveur MCP injoignable, Ollama injoignable) pour
    retourner un message clair plutôt qu'un 500 générique sans contexte.
    L'utilisateur doit comprendre CE QUI a échoué, pas juste QU'IL Y A eu
    un échec (voir palier 5, "erreurs visibles côté utilisateur")."""
    try:
        actions, excluded_actions, notice, trace = await planner.build_plan(body.prompt)
    except httpx.ConnectError as exc:
        logger.error("Connexion impossible (MCP ou Ollama) : %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Un service dont l'agent dépend est actuellement injoignable "
                "(serveur d'outils ou modèle IA). Réessayez dans quelques "
                "instants, ou contactez l'administrateur si le problème persiste."
            ),
        ) from exc
    except httpx.TimeoutException as exc:
        logger.error("Timeout pendant la planification : %s", exc)
        raise HTTPException(
            status_code=504,
            detail=(
                "La génération du plan a pris trop de temps et a été "
                "interrompue. Réessayez ; si le problème persiste, le "
                "modèle IA est peut-être surchargé ou indisponible."
            ),
        ) from exc
    except Exception as exc:
        # Filet de sécurité générique : on ne laisse jamais une exception
        # non prévue remonter brute (500 sans contexte) -- même sans
        # savoir précisément quoi s'est passé, on le dit clairement.
        logger.exception("Erreur inattendue pendant la planification")
        raise HTTPException(
            status_code=500,
            detail=(
                "Une erreur inattendue est survenue pendant la génération "
                "du plan. L'équipe technique a été notifiée (voir les logs)."
            ),
        ) from exc

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
    try:
        results = await executor.execute_actions(body.actions)
    except httpx.ConnectError as exc:
        logger.error("Connexion impossible au serveur MCP pendant l'exécution : %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "Le serveur d'outils est actuellement injoignable, "
                "impossible d'exécuter les actions. Réessayez dans "
                "quelques instants."
            ),
        ) from exc

    return {"results": results}
