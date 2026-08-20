"""
Implémentation réelle du tool "calendar" : génère un événement calendrier
au format .ics (RFC 5545), construit manuellement sans dépendance externe
(pas de package icalendar) -- choix de fiabilité pour rester dans le
budget restant avant le checkpoint, évite un nouveau paquet à installer
à ce stade avancé du hackathon. Suffisant pour un fichier .ics valide et
importable dans un client calendrier standard.

Écrit sous DATA_DIR/calendar/ et retourne le chemin du fichier comme
EventRef.
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from pydantic import Field

from mcp_instance import mcp
from domain_types import EventRef

_DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
_CALENDAR_DIR = _DATA_DIR / "calendar"

# Heure de début par défaut pour les événements générés (pas de créneau
# horaire précisé par le LLM à ce stade -- paramètre de contenu, valeur
# par défaut raisonnable, voir agent/planner.py sur cette distinction).
_DEFAULT_START_HOUR = 9


def _resolve_event_date(value: str) -> date:
    """Accepte une date ISO. Lève ValueError plutôt que d'inventer une
    date -- même principe que tools/tracker.py::_resolve_start_date."""
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
) -> EventRef:
    """Crée un événement calendrier (fichier .ics), typiquement pour une
    réunion d'accueil ou une présentation d'équipe. À utiliser seulement
    si l'intention mentionne explicitement un besoin de réunion --
    pas systématiquement pour tout onboarding. Retourne le chemin du
    fichier .ics généré."""
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

    _CALENDAR_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"event_{uid}.ics"
    filepath = _CALENDAR_DIR / filename
    filepath.write_text(ics_content, encoding="utf-8")

    return str(filepath)
