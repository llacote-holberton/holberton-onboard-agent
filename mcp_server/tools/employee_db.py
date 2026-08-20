"""
Implémentation réelle du tool "employee_db" : écrit la fiche employé,
avec validation stricte de l'équipe contre le même annuaire que celui
utilisé par mailbox.py (source de vérité unique, voir
mcp_server/tools/fixtures/employees_directory.json). Le LLM peut
halluciner une équipe -- ce tool la rejette avant tout effet de bord
plutôt que de faire confiance au prompt seul.
"""

import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Annotated

from pydantic import Field

from mcp_instance import mcp
from domain_types import EmployeeRef

# Même fixture que mailbox.py -- annuaire partagé, une seule source de
# vérité pour les noms d'équipe valides.
_DIRECTORY_PATH = Path(__file__).parent / "fixtures" / "employees_directory.json"
_DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
_EMPLOYEES_DB_PATH = _DATA_DIR / "employees.json"


def _load_known_teams() -> set[str]:
    with open(_DIRECTORY_PATH, encoding="utf-8") as f:
        departments = json.load(f)["departments"]
    return set(departments.keys())


def _load_employees() -> dict:
    if not _EMPLOYEES_DB_PATH.exists():
        return {}
    with open(_EMPLOYEES_DB_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_employees(employees: dict) -> None:
    _EMPLOYEES_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_EMPLOYEES_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(employees, f, ensure_ascii=False, indent=2)


@mcp.tool
def create_employee_record(
    name: Annotated[
        str,
        Field(description="Nom complet du nouveau collaborateur (ex: 'Léa Martin')."),
    ],
    role: Annotated[
        str,
        Field(description="Intitulé du poste (ex: 'Développeuse backend')."),
    ],
    team: Annotated[
        str,
        Field(
            description=(
                "Nom de l'équipe, doit correspondre exactement à une équipe "
                "existante dans l'annuaire interne (ex: 'Backend', 'Frontend'). "
                "Ne jamais deviner : utilise list_teams en cas de doute."
            )
        ),
    ],
    start_date: Annotated[
        date,
        Field(description="Date d'arrivée du collaborateur, au format ISO YYYY-MM-DD."),
    ],
) -> EmployeeRef:
    """Écrit la fiche du nouveau collaborateur en base. Rejette la demande
    si l'équipe indiquée n'existe pas dans l'annuaire interne -- ne fait
    jamais confiance à une équipe inventée, même si le modèle en a proposé
    une. Retourne l'identifiant unique de la fiche créée."""
    known_teams = _load_known_teams()
    if team not in known_teams:
        raise ValueError(
            f"Équipe inconnue : '{team}'. Équipes valides : {sorted(known_teams)}. "
            "L'action n'a pas été exécutée -- vérifiez le nom de l'équipe."
        )

    employee_id = str(uuid.uuid4())
    employees = _load_employees()
    employees[employee_id] = {
        "name": name,
        "role": role,
        "team": team,
        "start_date": start_date.isoformat(),
    }
    _save_employees(employees)

    return employee_id
