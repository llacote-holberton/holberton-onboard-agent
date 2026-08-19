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

import pydantic
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


# --- delete_employee_record (undo compensation) -----------------------


def test_delete_employee_record_removes_the_row_and_returns_true(tmp_path, monkeypatch):
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    employee_id = employee_db.create_employee_record(
        name="Camille Test", role="Dev", team="Backend", start_date=date(2026, 3, 3),
    )

    deleted = employee_db.delete_employee_record(employee_id)

    assert deleted is True
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row is None


def test_delete_employee_record_returns_false_for_unknown_id(tmp_path, monkeypatch):
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    deleted = employee_db.delete_employee_record("does-not-exist")

    assert deleted is False


def test_delete_employee_record_only_removes_the_targeted_row(tmp_path, monkeypatch):
    """Guards against a WHERE-less DELETE (or a wrong column) that would
    wipe every row instead of just the targeted one."""
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    keep_id = employee_db.create_employee_record(
        name="Keep Me", role="Dev", team="Backend", start_date=date(2026, 1, 1),
    )
    remove_id = employee_db.create_employee_record(
        name="Remove Me", role="Dev", team="Backend", start_date=date(2026, 1, 2),
    )

    deleted = employee_db.delete_employee_record(remove_id)

    assert deleted is True
    connection = sqlite3.connect(db_path)
    try:
        remaining_ids = {
            row[0] for row in connection.execute("SELECT id FROM employees").fetchall()
        }
    finally:
        connection.close()
    assert remaining_ids == {keep_id}


# --- `name` accepting `employee_name` (validation_alias) -----------------
#
# Repro from tonight's real run: the LLM called create_employee_record with
# `employee_name` instead of `name` (and dropped `team` entirely). The
# `team` omission has no clean fix (no honest default -- see the team=
# "all" discussion) but the `employee_name`/`name` mix-up is a genuine
# naming confusion an alias can absorb directly.
#
# These tests do NOT call employee_db.create_employee_record(...) as a
# plain Python function like the tests above -- a plain call bypasses
# Pydantic entirely (no validation happens on a normal function call), so
# it could never exercise validation_alias. They instead wrap the SAME
# function object with pydantic.validate_call, which is what actually
# reads Field(validation_alias=...) and resolves alternate input keys to
# the canonical parameter name before the function body runs -- the
# closest thing to FastMCP's own tool-calling behavior that could be
# verified without installing fastmcp itself (see the module docstring in
# employee_db.py for exactly what was and wasn't confirmed this way).


def test_create_employee_record_schema_does_not_expose_employee_name(tmp_path, monkeypatch):
    """The alias must stay purely an input-side convenience -- the JSON
    schema handed to the LLM (via agent/planner.py's tool discovery) should
    still show a single canonical "name" property, not "employee_name" or
    both. If this ever starts failing, something about how the alias was
    declared changed in a way that could confuse the LLM further instead of
    helping."""
    # model_json_schema() isn't directly reachable off a validate_call-
    # wrapped function the way it is off a BaseModel -- rebuild the same
    # Annotated signature as a throwaway BaseModel instead, which IS what
    # `model_json_schema()` is meant for, and is the same mechanism this
    # module's own docstring says was checked by hand.
    import inspect

    import pydantic as _pydantic

    sig = inspect.signature(employee_db.create_employee_record)
    fields = {name: (param.annotation, ...) for name, param in sig.parameters.items()}
    ThrowawayModel = _pydantic.create_model("ThrowawayModel", **fields)
    schema = ThrowawayModel.model_json_schema()

    assert "name" in schema["properties"]
    assert "employee_name" not in schema["properties"]


def test_create_employee_record_accepts_employee_name_as_an_alias_for_name(tmp_path, monkeypatch):
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    validated = pydantic.validate_call(employee_db.create_employee_record)

    employee_id = validated(
        employee_name="Camille",
        role="Développeuse Backend",
        team="Backend",
        start_date=date(2026, 8, 1),
    )

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT name FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row == ("Camille",)


def test_create_employee_record_still_accepts_name_directly(tmp_path, monkeypatch):
    """Guards against an alias declaration that accidentally replaces the
    canonical key instead of adding an alternative to it."""
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    validated = pydantic.validate_call(employee_db.create_employee_record)

    employee_id = validated(
        name="Camille", role="Développeuse Backend", team="Backend", start_date=date(2026, 8, 1),
    )

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT name FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row == ("Camille",)


def test_create_employee_record_defaults_team_to_a_placeholder_when_omitted(tmp_path, monkeypatch):
    """2026-08-20, plus tard la même session : le refus initial d'un défaut
    pour `team` (voir la docstring de create_employee_record et
    docs/TOOLS.md pour l'historique complet) est revu après une deuxième
    repro réelle consécutive où le LLM l'omet malgré la description déjà
    enrichie. Décision explicite de Laurent : accepter un défaut pour aller
    vite et passer le palier en cours, quitte à revenir dessus ensuite.

    Ce n'est pas la même situation que le `team="all"` écarté au premier
    tour : le placeholder retenu ne ressemble à aucun nom d'équipe
    plausible (voir _TEAM_PLACEHOLDER), ET agent/planner.py::_summarize a
    été corrigé en parallèle pour que ce genre de valeur reste visible dans
    le résumé d'approbation même quand le LLM omet le champ (voir
    agent/tests/test_planner.py) -- l'humain garde la main avant toute
    écriture en base."""
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    validated = pydantic.validate_call(employee_db.create_employee_record)

    employee_id = validated(
        employee_name="Camille", role="Développeuse Backend", start_date=date(2026, 8, 1)
    )

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT team FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row == (employee_db._TEAM_PLACEHOLDER,)


def test_create_employee_record_team_is_still_overridable(tmp_path, monkeypatch):
    """Guards against the new default silently winning even when `team` IS
    provided -- the whole point is to only kick in on omission."""
    db_path = tmp_path / "onboarding.db"
    monkeypatch.setattr(employee_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(employee_db, "DB_PATH", db_path)

    employee_id = employee_db.create_employee_record(
        name="Camille", role="Développeuse Backend", team="Backend", start_date=date(2026, 8, 1),
    )

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT team FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row == ("Backend",)
