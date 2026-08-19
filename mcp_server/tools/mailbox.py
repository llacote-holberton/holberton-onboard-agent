"""
Real implementation of the "mailbox" tool: sends a welcome message through
MailHog (fake SMTP), to real recipients resolved from a static employee
directory instead of a free-text `recipient` (see TOOLS.md "Annuaire
factice" and SEQUENCES.md diagram 5 -- the LLM must never invent an e-mail
address; if the department isn't in the directory, this raises instead of
guessing).

MessageRef (like every *Ref alias in domain_types.py) is just `str`, not a
class -- confirmed with Hugo. So the tool returns a plain string reference
rather than a constructed object: the generated Message-ID header of the
e-mail actually sent, which is a real, stable identifier (as opposed to a
made-up summary string) and is what MailHog itself indexes messages by.
"""

import json
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import make_msgid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from domain_types import MessageRef
from mcp_instance import mcp

# Resolved relative to this file, not the process cwd -- works no matter
# where mcp-server is actually started from.
_DIRECTORY_PATH = Path(__file__).parent / "fixtures" / "employees_directory.json"

MAILHOG_HOST = os.environ.get("MAILHOG_HOST", "mailhog")
MAILHOG_SMTP_PORT = int(os.environ.get("MAILHOG_SMTP_PORT", "1025"))

SENDER_ADDRESS = "onboarding-agent@holberton.example"


def _load_directory() -> dict:
    """Read fresh on every call rather than cached at import time -- the
    file is tiny, and this keeps the fixture editable without restarting
    mcp-server."""
    with open(_DIRECTORY_PATH, encoding="utf-8") as f:
        return json.load(f)["departments"]


def _resolve_recipients(team: str, channel: Literal["team", "manager", "it"]) -> list[str]:
    """Turns (team, channel) into real e-mail addresses -- see TOOLS.md
    "Annuaire factice" for the exact channel semantics. Raises ValueError
    (never a silently empty list, never an invented address) if the
    department isn't in the directory."""
    directory = _load_directory()
    department_name = "IT" if channel == "it" else team

    department = directory.get(department_name)
    if department is None:
        raise ValueError(f"Unknown department '{department_name}' in employees_directory.json")

    if channel == "manager":
        return [department["manager_email"]]
    return [member["email"] for member in department["members"]]


def _send_email(recipients: list[str], subject: str, body: str) -> str:
    """Sends the e-mail and returns its Message-ID -- the string reference
    this tool hands back as its MessageRef."""
    message_id = make_msgid(domain="onboarding-agent.local")

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = SENDER_ADDRESS
    message["To"] = ", ".join(recipients)
    message["Message-ID"] = message_id

    try:
        # timeout=10: fail fast and loud if MailHog is unreachable (e.g.
        # unplugged for the palier's "debrancher un outil" check), rather
        # than hanging the whole request.
        with smtplib.SMTP(MAILHOG_HOST, MAILHOG_SMTP_PORT, timeout=10) as client:
            client.sendmail(SENDER_ADDRESS, recipients, message.as_string())
    except OSError as exc:
        raise ConnectionError(f"Could not reach MailHog at {MAILHOG_HOST}:{MAILHOG_SMTP_PORT}: {exc}") from exc

    return message_id


@mcp.tool
def send_welcome_message(
    employee_name: Annotated[
        str,
        Field(description="Nom complet du nouveau collaborateur (ex: 'Léa Martin')."),
    ],
    team: Annotated[
        str,
        Field(
            description=(
                "Équipe d'accueil (ex: 'Backend') -- à extraire du contexte "
                "donné par l'utilisateur. Ignoré si channel='it'."
            )
        ),
    ],
    channel: Annotated[
        Literal["team", "manager", "it"],
        Field(
            description=(
                "Qui reçoit le message : 'team' envoie à tous les membres de "
                "`team`, 'manager' envoie uniquement au manager de `team`, "
                "'it' envoie toujours à l'équipe IT fixe, indépendamment de "
                "`team`. Par défaut 'team' si la demande ne précise pas de "
                "destinataire particulier -- c'est l'interprétation la plus "
                "probable d'un \"e-mail de bienvenue\" générique."
            )
        ),
    ] = "team",
) -> MessageRef:
    """Send a welcome notification about a new hire joining the company.

    NOTE (2026-08-19, repro observée en usage réel) : le LLM a omis
    `channel` entièrement sur un appel réel (missing_argument), alors que
    `employee_name`/`team` étaient corrects. `channel` a donc une valeur
    par défaut ("team") ajoutée après cet incident, contrairement à
    `team` sur create_employee_record (voir employee_db.py) qui reste
    volontairement SANS défaut. Distinction assumée, pas une
    contradiction : `team` sur create_employee_record est un FAIT sur la
    personne (son équipe réelle) -- une valeur inventée écrirait un
    mensonge en base, invisible dans le résumé d'approbation
    (_SUMMARY_TEMPLATES ne montre pas `team` pour ce tool). `channel` ici
    est un CHOIX de routage, pas un fait -- "team" est l'interprétation la
    plus large et la plus sûre d'une demande générique, ET ce choix reste
    visible dans le résumé d'approbation avant exécution
    (_SUMMARY_TEMPLATES affiche bien `{channel}` pour ce tool, voir
    agent/planner.py) -- l'humain peut donc encore refuser l'action si ce
    n'était pas l'intention. Même famille de limite LLM que le `checklist`
    par défaut de tracker.py et le `team` manquant d'hier -- pas une
    garantie totale avec un petit modèle local.

    Args:
        employee_name: Full name of the new hire, used in the message body.
        team: Department the new hire is joining (e.g. "Backend"). Used to
            look up real recipients in the internal directory. Ignored
            when channel is "it".
        channel: Who receives the message -- "team" sends to every member
            of `team`, "manager" sends only to `team`'s manager, "it"
            always sends to the fixed IT support team regardless of `team`.
            Defaults to "team" if omitted.

    Returns:
        The Message-ID of the e-mail actually sent (MessageRef is a plain
        `str` alias, see domain_types.py) -- kept for the audit trail.
        Note: undo for this tool can only ever be partial, an e-mail
        already delivered to MailHog cannot be unsent (see TOOLS.md).

    Raises:
        ValueError: `team` (or IT) is not in the employee directory --
            never guess or invent a recipient address instead.
        ConnectionError: MailHog is unreachable.
    """
    recipients = _resolve_recipients(team, channel)

    subject = f"Bienvenue à {employee_name} !"
    body = (
        f"Bonjour,\n\n"
        f"{employee_name} rejoint l'équipe {team} prochainement.\n"
        f"Merci de lui réserver un accueil chaleureux !\n\n"
        f"— L'agent d'onboarding"
    )
    return _send_email(recipients, subject, body)
