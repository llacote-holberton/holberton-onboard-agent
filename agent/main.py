import logging

import litellm
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import planner
import executor

app = FastAPI(title="Agent onboarding")

logger = logging.getLogger("agent")


def _provider_label() -> str:
    """Nom du fournisseur affiché dans les messages d'erreur -- le
    préfixe de LLM_MODEL_NAME (ex: "anthropic", "ollama") s'il y en a un,
    sinon le nom du modèle tel quel."""
    return planner._provider_prefix(planner.LLM_MODEL_NAME) or planner.LLM_MODEL_NAME


# DURCISSEMENT (2026-08-21, Laurent) -- palier "je casse", scénario 3 :
# "je coupe le réseau (ou je vous fais mettre une fausse clé d'API).
# Votre app doit le dire, pas boucler." Avant ce correctif, /plan et
# /execute laissaient filer TOUTE exception jusqu'à Starlette, qui répond
# alors par une page d'erreur 500 générique SANS corps JSON --
# describe_error() côté frontend (voir frontend/app.py) tombe alors sur
# un message technique illisible plutôt que la cause réelle. Chaque route
# ci-dessous attrape maintenant explicitement ces cas et renvoie un
# HTTPException avec un `detail` clair, qui remonte tel quel jusqu'à
# l'écran (agent -> backend/app/routers/plans.py ->
# frontend/app.py::describe_error) -- voir agent/tests/test_main.py pour
# la preuve que chaque scénario aboutit bien à un message explicite et
# jamais à un spinner qui tourne indéfiniment.
def _describe_llm_error(exc: Exception) -> tuple[int, str]:
    """Traduit une exception LiteLLM (ou toute autre) en (status_code
    HTTP, message utilisateur clair). LiteLLM calque sa hiérarchie
    d'exceptions sur celle du SDK OpenAI (litellm.AuthenticationError,
    RateLimitError, APIConnectionError, Timeout, BadRequestError,
    ServiceUnavailableError, InternalServerError, toutes sous litellm.
    APIError) QUEL QUE SOIT le fournisseur réellement actif -- vérifié
    d'abord par isinstance (précis), avec un filet générique basé sur le
    nom de la classe en dernier recours (robuste si LiteLLM lève une
    sous-classe plus spécifique que celles listées ici -- elle en définit
    une quinzaine au total)."""
    provider = _provider_label()
    exc_name = type(exc).__name__

    if isinstance(exc, getattr(litellm, "AuthenticationError", ())):
        return 502, (
            f"Le fournisseur LLM ({provider}) a refusé la clé API -- "
            "vérifiez LLM_MODEL_API_KEY (ou la variable spécifique au "
            "fournisseur, ex: ANTHROPIC_API_KEY) dans votre .env."
        )
    if isinstance(exc, getattr(litellm, "RateLimitError", ())):
        return 502, (
            f"Le fournisseur LLM ({provider}) a répondu : quota ou limite "
            "de débit dépassée -- réessayez dans un instant."
        )
    if isinstance(exc, getattr(litellm, "Timeout", ())):
        return 504, f"Le fournisseur LLM ({provider}) n'a pas répondu à temps (timeout) : {exc}"
    if isinstance(exc, getattr(litellm, "APIConnectionError", ())):
        # CORRECTIF (24/08, Laurent) -- {exc} ajouté ici : cette branche ne
        # remontait jusque-là que le message générique ci-dessous, jamais
        # le détail réel de l'exception LiteLLM sous-jacente (contrairement
        # aux branches BadRequestError/APIError plus bas). Repro observée
        # sur un prompt multi-actions lourd (Cas 2) : LiteLLM classe parfois
        # un VRAI timeout de génération en APIConnectionError plutôt qu'en
        # Timeout pour les fournisseurs locaux (ollama_chat) -- sans {exc}
        # ici, impossible de distinguer ce cas d'un vrai problème réseau/
        # conteneur arrêté juste en lisant le message affiché à l'écran.
        return 503, (
            f"Impossible de joindre le fournisseur LLM ({provider}) -- "
            "réseau indisponible ou service injoignable. Vérifiez votre "
            "connexion et, si LLM_MODEL_NAME commence par 'ollama_chat/' "
            "ou 'ollama/', que le conteneur ollama est bien démarré "
            f"(--profile local-llm, voir README.md). Détail technique : {exc}"
        )
    if isinstance(exc, getattr(litellm, "BadRequestError", ())):
        return 400, f"Le fournisseur LLM ({provider}) a rejeté la requête : {exc}"
    if isinstance(exc, (getattr(litellm, "ServiceUnavailableError", ()), getattr(litellm, "InternalServerError", ()))):
        return 502, f"Le fournisseur LLM ({provider}) est actuellement indisponible : {exc}"
    if isinstance(exc, getattr(litellm, "APIError", ())):
        return 502, f"Le fournisseur LLM ({provider}) a répondu une erreur : {exc}"

    lowered = exc_name.lower()
    if "auth" in lowered or "permission" in lowered:
        return 502, f"Le fournisseur LLM ({provider}) a refusé l'authentification ({exc_name})."
    if "timeout" in lowered:
        return 504, f"Le fournisseur LLM ({provider}) n'a pas répondu à temps ({exc_name})."
    if "connect" in lowered:
        return 503, f"Impossible de joindre le fournisseur LLM ({provider}) ({exc_name})."
    if "ratelimit" in lowered or "rate_limit" in lowered:
        return 502, f"Le fournisseur LLM ({provider}) : quota dépassé ({exc_name})."

    # Dernier recours : ne JAMAIS laisser une exception non prévue
    # remonter nue jusqu'à Starlette (palier "ça doit le dire, pas
    # boucler" -- un message générique mais explicite vaut mieux qu'un
    # 500 sans corps JSON que le frontend ne peut pas afficher proprement).
    return 500, f"Erreur inattendue lors de l'appel au fournisseur LLM ({provider}, {exc_name}) : {exc}"


@app.get("/ping-llm")
async def ping_llm():
    """Vérification optionnelle (palier 2) : un aller-retour réel avec le
    fournisseur LLM actif (LLM_MODEL_NAME, quel qu'il soit -- voir
    planner.py) via LiteLLM, comme /plan. Peut échouer/timeout
    indépendamment de ce code (ex: pas assez de RAM pour charger un
    modèle Ollama local, clé API absente...) -- voir /ping ci-dessous
    pour un check plus léger qui ne dépend pas du LLM."""
    try:
        # Réutilise EXACTEMENT le même timeout que build_plan() pour un
        # tour (planner._LLM_CALL_TIMEOUT, dérivé de LLM_CALL_TIMEOUT_SECONDS
        # -- voir son commentaire) : ping_llm() ne fait lui aussi qu'UN
        # seul appel LLM, aucune raison d'avoir une valeur en dur séparée
        # à retenir de corriger à la main à chaque fois (24/08, Laurent --
        # correctif suite à une valeur en dur oubliée ici).
        response = await litellm.acompletion(
            model=planner.LLM_MODEL_NAME,
            messages=[{"role": "user", "content": "Réponds en une phrase : que fais-tu ?"}],
            timeout=planner._LLM_CALL_TIMEOUT,
        )
        return {"model": planner.LLM_MODEL_NAME, "response": response.choices[0].message.content}
    except Exception as exc:
        status_code, detail = _describe_llm_error(exc)
        # logger.exception (au lieu de logger.error) : capture la trace
        # Python complète côté logs agent, même si le message affiché à
        # l'utilisateur (detail) reste condensé -- correctif du même
        # ordre que celui de _describe_llm_error ci-dessus (24/08, Laurent).
        logger.exception("ping_llm a échoué (%s)", type(exc).__name__)
        raise HTTPException(status_code=status_code, detail=detail) from exc


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
    try:
        actions, excluded_actions, notice = await planner.build_plan(body.prompt)
    except Exception as exc:
        status_code, detail = _describe_llm_error(exc)
        # logger.exception : voir le même correctif sur ping_llm() ci-dessus.
        logger.exception("build_plan a échoué (%s)", type(exc).__name__)
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return {"actions": actions, "excluded_actions": excluded_actions, "clarification": notice}


class ExecuteRequest(BaseModel):
    actions: list[dict]


@app.post("/execute")
async def execute(body: ExecuteRequest):
    try:
        results = await executor.execute_actions(body.actions)
    except Exception as exc:
        # execute_actions() attrape déjà les erreurs PAR ACTION (une
        # action qui échoue devient un résultat {"status": "error", ...}
        # sans faire échouer les autres -- voir executor.py). Ce qui
        # arrive ICI, c'est donc un échec plus structurel : le serveur
        # MCP lui-même est injoignable (réseau coupé, service down) avant
        # même de pouvoir dispatcher la moindre action.
        detail = (
            "Impossible de contacter le serveur MCP pour exécuter les "
            f"actions ({type(exc).__name__}) : {exc}"
        )
        logger.error(detail)
        raise HTTPException(status_code=502, detail=detail) from exc
    return {"results": results}
