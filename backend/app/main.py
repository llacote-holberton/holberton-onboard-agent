"""
Version minimale, juste pour vérifier que le container démarre, écoute sur le
bon port, et répond au healthcheck défini dans docker-compose.yml.
Pas de DB, pas de routers, pas d'appel à agent/mcp-server pour l'instant —
tout ça arrive aux étapes suivantes.
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
