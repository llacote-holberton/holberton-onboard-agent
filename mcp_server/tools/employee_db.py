"""
Real implementation of the "employee_db" tool: writes the new hire's record
to the SAME SQLite database as the backend.

mcp-server is a separate process/container from backend (see
docker-compose.yml), so it cannot import `app.models.Employee` -- that
package lives in the backend service only. Instead this module talks to
the shared file directly via the stdlib `sqlite3`, mirroring the exact
table shape SQLAlchemy's Employee model declares (backend/app/models.py):
same table name ("employees"), same columns. Whichever service's process
starts first creates the table (CREATE TABLE IF NOT EXISTS), the other
reuses it as-is -- no fixed startup order is assumed between the two
services. Keep _CREATE_TABLE_SQL in sync with models.py::Employee by hand
if that model ever changes; there is no shared source of truth between the
two services for this schema.

Concurrency: two separate processes writing to the same SQLite file is the
same situation backend/app/database.py already documents and handles for
its own connections (see its "Point de vigilance" docstring) -- WAL mode +
a busy_timeout are set on every connection opened here too, for the same
reason.
"""

import os
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field

from domain_types import EmployeeRef
from mcp_instance import mcp

# Same env var, same default shape as backend/app/config.py's DATA_DIR --
# docker-compose.yml sets DATA_DIR identically for both services, so this
# resolves to the exact same file on disk as backend's DATABASE_PATH.
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "onboarding.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS employees (
    id VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    team VARCHAR NOT NULL,
    start_date DATE NOT NULL,
    created_at DATETIME
)
"""


# Valeur de repli pour `team` quand le LLM l'omet -- voir la docstring de
# create_employee_record ci-dessous pour l'historique complet de cette
# décision (revenue en arrière le 2026-08-20, plus tard la même session).
# Choisie pour ne ressembler à aucun nom d'équipe plausible (contrairement
# à "all", envisagé puis écarté au premier tour) : si elle apparaît sur le
# résumé d'approbation, elle doit sauter aux yeux comme un placeholder à
# corriger, pas comme une vraie équipe passée inaperçue.
_TEAM_PLACEHOLDER = "À préciser"


def _connect() -> sqlite3.Connection:
    """Module-level DATA_DIR/DB_PATH are read here (not captured in a
    closure) so tests can monkeypatch them per-case without reloading the
    module."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=5)
    # Same reasoning as backend/app/database.py's _set_sqlite_pragmas:
    # reduces lock contention with the backend process writing to the same
    # file concurrently.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


@mcp.tool
def create_employee_record(
    name: Annotated[
        str,
        Field(
            validation_alias=AliasChoices("name", "employee_name"),
            description="Nom complet du nouveau collaborateur (ex: 'Léa Martin').",
        ),
    ],
    role: Annotated[
        str,
        Field(description="Intitulé de poste (ex: 'Développeuse Backend')."),
    ],
    start_date: Annotated[
        date,
        Field(description="Date d'arrivée du collaborateur, au format ISO (AAAA-MM-JJ)."),
    ],
    team: Annotated[
        str,
        Field(
            description=(
                "Équipe d'accueil (ex: 'Backend') -- à extraire du contexte "
                "donné par l'utilisateur (souvent mentionnée à côté du rôle "
                "ou du poste, ex: 'nouvelle développeuse dans l'équipe "
                "Backend'). Ne jamais l'omettre si l'information est "
                "disponible dans la demande. Si malgré tout absente, une "
                f"valeur de repli ('{_TEAM_PLACEHOLDER}') est utilisée -- "
                "visible dans le résumé d'approbation, à corriger ou "
                "refuser côté humain plutôt que de bloquer l'action."
            )
        ),
    ] = _TEAM_PLACEHOLDER,
) -> EmployeeRef:
    """Écrit la fiche du nouveau collaborateur en base.

    NOTE (2026-08-20, repro observée en usage réel) : le paramètre
    ci-dessous s'appelle `name`, PAS `employee_name` -- contrairement à
    create_onboarding_issue et send_welcome_message, qui utilisent bien
    `employee_name`. Un run réel a vu le LLM confondre les deux
    conventions (appel avec `employee_name` au lieu de `name`, et `team`
    complètement omis), rejeté par la validation Pydantic mcp-server.
    Descriptions ci-dessous enrichies suite à cet incident pour réduire le
    risque de récidive -- pas de garantie totale avec un petit modèle local
    (même famille de limite que le `checklist` manquant documenté dans
    tracker.py).

    `name` accepte aussi `employee_name` en entrée (validation_alias, voir
    l'import AliasChoices) -- patch direct de la confusion observée, en
    plus des descriptions enrichies. Vérifié (2026-08-20) contre le vrai
    pydantic 2.13.3 (celui de l'erreur reçue) : `model_json_schema()`
    continue d'exposer "name" comme unique propriété (pas de fuite de
    "employee_name" vers le LLM), et `validate_call` sur une fonction
    reproduisant exactement cette signature résout bien `employee_name=...`
    vers le paramètre `name` à l'appel. Cette dernière partie teste le
    mécanisme Pydantic lui-même, PAS le passage réel par FastMCP
    (`@mcp.tool` -> `call_tool()` -> cette fonction) -- toujours pas
    vérifiable sans accès PyPI dans ce bac à sable. Voir
    mcp_server/tests/test_employee_db.py pour le test correspondant.

    MISE À JOUR (2026-08-20, plus tard la même session) : `team` recevait
    volontairement AUCUN défaut jusqu'ici (voir l'historique ci-dessus et
    docs/TOOLS.md) -- décision revue après une deuxième repro réelle
    consécutive où le LLM l'omet malgré la description déjà enrichie.
    Décision explicite de Laurent : accepter un défaut pour aller vite et
    passer le palier en cours, quitte à revenir dessus ensuite si besoin.
    Différence assumée avec le `"all"` écarté au premier tour : le
    placeholder retenu (`_TEAM_PLACEHOLDER`, "À préciser") ne ressemble à
    aucun nom d'équipe plausible, ET `agent/planner.py::_SUMMARY_TEMPLATES`
    a été mis à jour pour afficher `{team}` dans le résumé d'approbation de
    ce tool (il ne l'affichait pas avant, ce qui rendait un défaut
    invisible et donc risqué) -- l'humain voit encore la valeur retenue et
    peut refuser l'action avant toute écriture en base si elle ne convient
    pas. Reste un pis-aller : la ligne est bien écrite avec ce placeholder
    si l'humain approuve sans vérifier ; pas un problème nouveau (même
    risque que pour `channel` sur send_welcome_message), mais à garder en
    tête si ce champ est fréquemment mal renseigné en pratique.

    Args:
        name: Nom complet du nouveau collaborateur (ex: "Léa Martin").
        role: Intitulé de poste (ex: "Développeuse Backend").
        start_date: Date d'arrivée du collaborateur.
        team: Équipe d'accueil (ex: "Backend"). Par défaut "À préciser" si
            omise (voir la note ci-dessus).

    Returns:
        L'ID de la ligne insérée (EmployeeRef est un simple alias de `str`,
        voir domain_types.py) -- c'est cet ID que generate_handbook attend
        en `employee_id` (voir docs/TOOLS.md), et celui que
        delete_employee_record recevra le jour où l'annulation de ce tool
        sera implémentée.
    """
    employee_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    connection = _connect()
    try:
        connection.execute(_CREATE_TABLE_SQL)
        connection.execute(
            "INSERT INTO employees (id, name, role, team, start_date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (employee_id, name, role, team, start_date.isoformat(), created_at),
        )
        connection.commit()
    finally:
        connection.close()

    return employee_id


@mcp.tool
def delete_employee_record(employee: EmployeeRef) -> bool:
    """Fonction de compensation de create_employee_record (voir docs/TOOLS.md
    "Fonctions de compensation") : supprime la ligne de la base.

    Outil INTERNE, jamais exposé au LLM au moment du plan -- voir
    agent/planner.py::_INTERNAL_ONLY_TOOLS. Appelé uniquement par le backend
    lors d'une annulation (POST /actions/{id}/undo), avec `employee` égal à
    l'EmployeeRef que create_employee_record avait renvoyé (stocké tel quel
    dans Action.result -- voir backend/app/services/mcp_client.py).

    Returns:
        True si une ligne a bien été supprimée. False si `employee` ne
        correspond à aucune ligne existante (déjà supprimée, ou id invalide)
        -- pas une exception : ce n'est pas un échec technique, juste un
        signal explicite que l'appelant peut choisir d'interpréter comme un
        échec d'annulation (c'est le choix fait côté mcp_client.py) plutôt
        que de rapporter un succès sur rien.
    """
    connection = _connect()
    try:
        connection.execute(_CREATE_TABLE_SQL)
        cursor = connection.execute("DELETE FROM employees WHERE id = ?", (employee,))
        connection.commit()
        deleted = cursor.rowcount > 0
    finally:
        connection.close()

    return deleted
