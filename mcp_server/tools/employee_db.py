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
    name: str,
    role: str,
    team: str,
    start_date: date,
) -> EmployeeRef:
    """Écrit la fiche du nouveau collaborateur en base.

    Args:
        name: Nom complet du nouveau collaborateur (ex: "Léa Martin").
        role: Intitulé de poste (ex: "Développeuse Backend").
        team: Équipe d'accueil (ex: "Backend").
        start_date: Date d'arrivée du collaborateur.

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
