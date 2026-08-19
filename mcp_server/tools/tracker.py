import os
from datetime import date, timedelta
from typing import Annotated

import httpx
from pydantic import Field

from mcp_instance import mcp
from domain_types import IssueRef

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_API_BASE = "https://api.github.com"

# Checklist standard utilisee quand le LLM omet le parametre `checklist` --
# repro observee en pratique avec qwen3:0.6b (missing_argument sur ce champ,
# les deux autres champs remplis correctement). Un defaut documente et
# raisonnable, pas une invention de donnee externe (contrairement a un
# email hallucine dans mailbox.py) -- on assume ce choix plutot que de
# planter l'appel a chaque fois que le modele oublie ce champ.
_DEFAULT_CHECKLIST = [
    "Créer le compte et les accès (email, Slack, VPN)",
    "Préparer le poste de travail",
    "Planifier l'accueil avec l'équipe",
]


def _sanitize_checklist(value) -> list[str]:
    """Repro observee : qwen3:0.6b renvoie parfois pour `checklist` un
    fragment du JSON Schema de l'outil lui-meme (ex. un item valant
    {"type": "array", "items": {"type": "string"}}) au lieu d'une vraie
    liste de taches -- confond la structure attendue avec le contenu.
    Avec `checklist: list[str]` strict, Pydantic rejette l'appel entier
    AVANT que ce fichier ne s'execute, donc un simple `checklist or
    _DEFAULT_CHECKLIST` dans le corps de la fonction n'a jamais la main.
    Le parametre est donc assoupli en entree (voir l'annotation plus bas,
    `list | None`) et c'est cette fonction qui filtre : ne garde que les
    elements qui sont reellement des chaines non vides, et retombe sur la
    checklist par defaut si rien d'exploitable ne reste -- salvage partiel
    plutot que tout rejeter pour un seul element mal forme."""
    if not isinstance(value, list):
        return _DEFAULT_CHECKLIST
    items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return items or _DEFAULT_CHECKLIST

# Jour de la semaine -> index ISO (lundi=0 ... dimanche=6). Repro observee
# en pratique : qwen3:0.6b, avec le mode reflexion desactive ("think":
# False cote agent/planner.py), a du mal a convertir lui-meme "lundi" en
# une date ISO absolue malgre la date du jour donnee dans le prompt
# systeme -- renvoie le mot litteral, que Pydantic rejette (le champ etait
# type `date`). Plutot que de compter sur le LLM pour ce calcul, le tool
# le fait lui-meme, de facon deterministe.
_FRENCH_WEEKDAYS = {
    "lundi": 0,
    "mardi": 1,
    "mercredi": 2,
    "jeudi": 3,
    "vendredi": 4,
    "samedi": 5,
    "dimanche": 6,
}


def _resolve_start_date(value: str) -> date:
    """Accepte une date ISO (ex. "2026-08-24") ou un jour de la semaine en
    français (ex. "lundi"), "aujourd'hui" ou "demain" -- résolu à la
    prochaine occurrence de ce jour à partir d'aujourd'hui (aujourd'hui
    inclus). Lève ValueError si rien ne correspond, plutôt que d'inventer
    une date -- même principe que l'annuaire de mailbox.py : un échec
    explicite, jamais une valeur devinée en silence."""
    text = value.strip().lower()

    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        pass

    today = date.today()
    if text in ("aujourd'hui", "aujourdhui"):
        return today
    if text == "demain":
        return today + timedelta(days=1)
    if text in _FRENCH_WEEKDAYS:
        delta = (_FRENCH_WEEKDAYS[text] - today.weekday()) % 7
        return today + timedelta(days=delta)

    raise ValueError(
        f"Date de début '{value}' non reconnue -- utilise une date ISO "
        "(AAAA-MM-JJ) ou un jour de la semaine en français (ex. 'lundi')."
    )


@mcp.tool
async def create_onboarding_issue(
    employee_name: Annotated[
        str,
        Field(description="Nom complet du nouveau collaborateur (ex: 'Léa Martin')."),
    ],
    start_date: Annotated[
        str,
        Field(
            description=(
                "Date d'arrivée du collaborateur. Format ISO préféré "
                "(AAAA-MM-JJ, ex: '2026-08-24'), mais un jour de la semaine "
                "en français (ex: 'lundi'), 'aujourd'hui' ou 'demain' est "
                "aussi accepté -- résolu à la prochaine occurrence de ce "
                "jour à partir d'aujourd'hui."
            )
        ),
    ],
    checklist: Annotated[
        list | None,
        Field(
            description=(
                "Liste des tâches à accomplir avant ou pendant l'arrivée, "
                "chaque élément étant une chaîne de texte "
                "(ex: ['Créer le compte', 'Préparer le poste de travail', "
                "'Badge d'accès']). Optionnel -- si omise, une checklist "
                "standard par défaut est utilisée."
            )
        ),
    ] = None,
) -> IssueRef:
    """Crée un ticket de suivi (issue GitHub) pour tracer l'ensemble des
    tâches d'onboarding d'un nouveau collaborateur. À utiliser dès qu'un
    plan d'onboarding est lancé, pour centraliser le suivi des tâches
    associées dans le tracker de l'équipe. Retourne l'URL de l'issue créée."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise RuntimeError(
            "GITHUB_TOKEN et GITHUB_REPO doivent être définis dans l'environnement "
            "(voir .env.example)."
        )

    resolved_start_date = _resolve_start_date(start_date)

    checklist = _sanitize_checklist(checklist)
    checklist_md = "\n".join(f"- [ ] {item}" for item in checklist)
    body = (
        f"## Onboarding — {employee_name}\n\n"
        f"**Date d'arrivée** : {resolved_start_date.isoformat()}\n\n"
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
