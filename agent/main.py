# agent/main.py — ajout minimal pour palier 2
from fastapi import FastAPI
import httpx
import os

app = FastAPI(title="Agent onboarding")

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

@app.get("/ping-llm")
async def ping_llm():
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{OLLAMA_API_BASE}/api/generate", json={
            "model": OLLAMA_MODEL,
            "prompt": "Réponds en une phrase : que fais-tu ?",
            "stream": False
        })
        return r.json()
