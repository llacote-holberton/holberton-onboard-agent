import os
from datetime import date

import httpx

from mcp_instance import mcp
from domain_types import IssueRef

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_API_BASE = "https://api.github.com"


@mcp.tool
async def create_onboarding_issue(
    employee_name: str,
    start_date: date,
    checklist: list[str],
) -> IssueRef:
    """Crée un ticket/epic d'onboarding sur le tracker (GitHub Issues)."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError(
            "GITHUB_TOKEN et GITHUB_REPO doivent être définis dans l'environnement "
            "(voir .env.example)."
        )

    checklist_md = "\n".join(f"- [ ] {item}" for item in checklist)
    body = (
        f"## Onboarding — {employee_name}\n\n"
        f"**Date d'arrivée** : {start_date.isoformat()}\n\n"
        f"### Checklist\n{checklist_md}\n"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": f"Onboarding — {employee_name}",
                "body": body,
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["html_url"]
