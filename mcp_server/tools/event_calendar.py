"""
Implémentation réelle du tool "calendar" : génère un événement calendrier
au format .ics (RFC 5545), construit manuellement sans dépendance externe
(pas de package icalendar) -- choix de fiabilité pour rester dans le
budget restant avant le checkpoint, évite un nouveau paquet à installer
à ce stade avancé du hackathon. Suffisant pour un fichier .ics valide et
importable dans un client calendrier standard.

Écrit sous DATA_DIR/calendar/ et retourne le chemin du fichier comme
EventRef.

RÉCONCILIATION (2026-08-20, Laurent) : implémentation reprise depuis
Feature/palier3 (Hugo) -- dev_laurent n'avait qu'un stub
(`raise NotImplementedError`) pour ce tool. Deux ajustements par rapport
à l'original de Hugo : (1) `event_date` en `str` + résolution manuelle
(`_resolve_event_date`) plutôt qu'un type `date` Pydantic strict -- le
stub de dev_laurent utilisait `date`, mais ça diverge de la convention
déjà établie ailleurs dans ce projet pour les dates fournies par le LLM
(voir tools/tracker.py::_resolve_start_date, qui accepte aussi des
formulations relatives) ; ISO uniquement ici (pas de "lundi prochain"),
mais toujours via une fonction de résolution explicite plutôt qu'un type
qui ferait échouer l'appel avec une erreur Pydantic générique et peu
lisible en cas de format inattendu. (2) DATA_DIR aligné sur la convention
établie par employee_db.py (`./data` résolu en absolu, pas `/app/data` en
dur) -- sans effet en Docker (docker-compose.yml fixe DATA_DIR
explicitement), nécessaire pour les scripts/tests hors conteneur.

RÉCONCILIATION 2026-08-20 (Laurent) -- association plan_id : même
mécanisme que tools/documents.py (voir sa docstring de module pour le
détail) -- le fichier .ics est rangé sous CALENDAR_DIR/<plan_id>/ quand
un plan_id est fourni. `_resolve_target_dir` est dupliqué ici plutôt que
partagé avec documents.py, par cohérence avec la convention déjà en
place dans ce module (DATA_DIR/CALENDAR_DIR déjà dupliqués eux aussi
plutôt que mutualisés).
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from pydantic import Field

from mcp_instance import mcp
from domain_types import EventRef

# Même convention que employee_db.py::DATA_DIR.
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
CALENDAR_DIR = DATA_DIR / "calendar"


def _resolve_target_dir(plan_id: str | None) -> Path:
    """Voir tools/documents.py::_resolve_target_dir -- même logique."""
    if not plan_id:
        return CALENDAR_DIR
    if "/" in plan_id or "\\" in plan_id or ".." in plan_id:
        raise ValueError(f"plan_id invalide : '{plan_id}'.")
    return CALENDAR_DIR / plan_id

# Heure de début par défaut pour les événements générés (pas de créneau
# horaire précisé par le LLM à ce stade -- paramètre de contenu, valeur
# par défaut raisonnable, voir agent/planner.py sur cette distinction).
_DEFAULT_START_HOUR = 9


def _resolve_event_date(value: str) -> date:
    """Accepte une date ISO. Lève ValueError plutôt que d'inventer une
    date -- même principe que tools/tracker.py::_resolve_start_date, en
    plus strict (ISO uniquement, pas de formulation relative comme
    "lundi" -- pas nécessaire ici, à revoir si un jour utile)."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(
            f"Date d'événement '{value}' non reconnue -- utilise le "
            "format ISO (AAAA-MM-JJ)."
        ) from exc


def _attendee_line(name: str) -> str:
    """Convertit un nom/email en ligne ATTENDEE .ics. Si `name` ressemble
    déjà à un email, l'utilise tel quel ; sinon construit une adresse
    factice à partir du nom (démo uniquement, pas un vrai annuaire ici
    contrairement à mailbox.py)."""
    if "@" in name:
        email = name
    else:
        email = name.strip().lower().replace(" ", ".") + "@holberton.example"
    return f"ATTENDEE;CN={name}:mailto:{email}"


@mcp.tool
def create_calendar_event(
    title: Annotated[
        str,
        Field(description="Titre de l'événement (ex: 'Présentation de Léa à l'équipe')."),
    ],
    event_date: Annotated[
        str,
        Field(description="Date de l'événement, au format ISO (AAAA-MM-JJ)."),
    ],
    duration_minutes: Annotated[
        int,
        Field(description="Durée de l'événement en minutes (ex: 30, 60). Doit être positive."),
    ],
    attendees: Annotated[
        list[str],
        Field(
            description=(
                "Liste des noms ou emails des participants à inviter "
                "(ex: ['Léa Martin', 'manager@entreprise.com'])."
            )
        ),
    ],
    plan_id: Annotated[
        str | None,
        Field(
            description=(
                "Réservé au système -- NE JAMAIS renseigner ce champ "
                "toi-même, la valeur que tu fournirais serait de toute "
                "façon ignorée et remplacée."
            )
        ),
    ] = None,
) -> EventRef:
    """Crée un événement calendrier (fichier .ics), typiquement pour une
    réunion d'accueil ou une présentation d'équipe. À utiliser seulement
    si l'intention mentionne explicitement un besoin de réunion --
    pas systématiquement pour tout onboarding. Retourne le chemin du
    fichier .ics généré (EventRef, alias de str)."""
    parsed_date = _resolve_event_date(event_date)

    if duration_minutes <= 0:
        raise ValueError("La durée de l'événement doit être positive.")

    start = datetime(
        parsed_date.year, parsed_date.month, parsed_date.day,
        _DEFAULT_START_HOUR, 0,
    )
    end = start + timedelta(minutes=duration_minutes)
    uid = str(uuid.uuid4())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    attendee_lines = "\n".join(_attendee_line(a) for a in attendees)

    ics_content = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Onboard-Agent//FR\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{stamp}\r\n"
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}\r\n"
        f"SUMMARY:{title}\r\n"
        f"{attendee_lines}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    target_dir = _resolve_target_dir(plan_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"event_{uid}.ics"
    filepath = target_dir / filename
    filepath.write_text(ics_content, encoding="utf-8")

    return str(filepath)
