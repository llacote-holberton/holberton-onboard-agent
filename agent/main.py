from fastapi import FastAPI
from pydantic import BaseModel
import httpx
import os

import planner
import executor

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

class PlanRequest(BaseModel):
    prompt: str


@app.post("/plan")
async def plan(body: PlanRequest):
    actions = await planner.build_plan(body.prompt)
    return {"actions": actions}


class ExecuteRequest(BaseModel):
    actions: list[dict]


@app.post("/execute")
async def execute(body: ExecuteRequest):
    results = await executor.execute_actions(body.actions)
    return {"results": results}
