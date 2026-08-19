"""
Unit tests for the employee_db tool (mcp_server/tools/employee_db.py).

No mocking of an external service here (unlike tracker.py's GitHub call or
mailbox.py's SMTP call) -- create_employee_record only touches a local
SQLite file, so these tests exercise the real code path end to end against
a temporary DB (tmp_path), and assert directly on what actually landed on
disk, rather than on a mock's call args.

Confirmed against a real local run (Laurent, 2026-08-20, fastmcp per
mcp_server/requirements.txt, Python 3.14.4): `@mcp.tool` does NOT wrap the
function in a Tool object here -- it registers it as a side effect and
returns the original function unchanged (`type(create_employee_record) is
function`). So it's called directly below, no `.fn` indirection needed --
an earlier version of this file assumed FastMCP always returns a Tool
wrapper exposing `.fn`; that assumption was wrong for this version and has
been corrected after the AttributeError it predicted actually fired.
"""

import sqlite3
from datetime import date

from tools import employee_db


def test_create_employee_record_writes_row_and_returns_its_id(tmp_path, monkeypatch):
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    employee_id = employee_db.create_employee_record(
        name="Camille Test",
        role="Développeuse Backend",
        team="Backend",
        start_date=date(2026, 3, 3),
    )

    assert isinstance(employee_id, str) and employee_id

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT id, name, role, team, start_date FROM employees WHERE id = ?",
            (employee_id,),
        ).fetchone()
    finally:
        connection.close()

    assert row == (employee_id, "Camille Test", "Développeuse Backend", "Backend", "2026-03-03")


def test_create_employee_record_creates_table_if_missing(tmp_path, monkeypatch):
    """Table must be created on the fly if mcp-server's process happens to
    handle the first insert before backend's own init_db() has ever run --
    no fixed startup order is assumed between the two services (see
    employee_db.py's module docstring)."""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)
    assert not db_path.exists()

    employee_db.create_employee_record(
        name="Léa Martin", role="Product Manager", team="Product", start_date=date(2026, 4, 1),
    )

    assert db_path.exists()


def test_create_employee_record_two_calls_get_distinct_ids(tmp_path, monkeypatch):
    """Guards against a careless id scheme (e.g. reusing rowid as the
    returned ref) that would silently collide two employees created in the
    same run."""
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    first_id = employee_db.create_employee_record(
        name="A", role="R", team="Backend", start_date=date(2026, 1, 1),
    )
    second_id = employee_db.create_employee_record(
        name="B", role="R", team="Backend", start_date=date(2026, 1, 2),
    )

    assert first_id != second_id

    connection = sqlite3.connect(db_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    finally:
        connection.close()
    assert count == 2
