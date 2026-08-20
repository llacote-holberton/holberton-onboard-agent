"""
Tests for GET /actions/{id}/download (RECONCILIATION 2026-08-20, Laurent --
plan_id association + download feature).

Split out from test_actions_api.py into its own file: these tests target
app.routers.actions.download_action_file and app.config.FILE_GENERATING_
TOOLS, both introduced alongside this file -- keeping them together with
the feature they cover makes the dependency obvious (this file cannot pass
on its own before that code exists), and avoids mixing them into
test_actions_api.py's pre-existing, unrelated coverage of the approve/
refuse/undo endpoints.

_make_action() below is a deliberate copy of test_actions_api.py's helper
(already fixed there for the tool=/params= override case this file needs)
rather than a cross-file import -- same "duplicate small helpers instead of
sharing across modules" convention already used in this codebase (see
mcp_server/tools/documents.py and event_calendar.py's own
_resolve_target_dir).
"""

from app.models import Action, Plan


def _make_action(db_session, **overrides):
    plan = Plan(prompt="onboard Jane Doe")
    defaults = {
        "tool": "create_onboarding_issue",
        "params": {"employee": "Jane Doe"},
        "summary": "Create the onboarding issue",
        "idempotency_key": "key-1",
    }
    action = Action(**{**defaults, **overrides})
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(action)
    return action


def test_download_404_when_action_does_not_exist(client):
    response = client.get("/actions/does-not-exist/download")

    assert response.status_code == 404


def test_download_400_when_tool_does_not_generate_a_file(client, db_session):
    action = _make_action(db_session, status="executed", result={"issue_id": "ISSUE-1"})

    response = client.get(f"/actions/{action.id}/download")

    assert response.status_code == 400


def test_download_409_when_action_not_yet_executed(client, db_session):
    action = _make_action(db_session, tool="generate_handbook", status="approved")

    response = client.get(f"/actions/{action.id}/download")

    assert response.status_code == 409


def test_download_404_when_file_missing_from_disk(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr("app.routers.actions.DATA_DIR", tmp_path)
    action = _make_action(
        db_session,
        tool="generate_handbook",
        status="executed",
        result=str(tmp_path / "documents" / "does-not-exist.pdf"),
    )

    response = client.get(f"/actions/{action.id}/download")

    assert response.status_code == 404


def test_download_404_when_result_path_escapes_data_dir(client, db_session, monkeypatch, tmp_path):
    outside = tmp_path.parent / "outside-data-dir.pdf"
    outside.write_bytes(b"%PDF-1.4 fake")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("app.routers.actions.DATA_DIR", data_dir)
    action = _make_action(
        db_session,
        tool="generate_handbook",
        status="executed",
        result=str(outside),
    )

    response = client.get(f"/actions/{action.id}/download")

    assert response.status_code == 404


def test_download_returns_the_generated_file(client, db_session, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    documents_dir = data_dir / "documents" / "plan-123"
    documents_dir.mkdir(parents=True)
    generated = documents_dir / "handbook.pdf"
    generated.write_bytes(b"%PDF-1.4 fake handbook content")
    monkeypatch.setattr("app.routers.actions.DATA_DIR", data_dir)
    action = _make_action(
        db_session,
        tool="generate_handbook",
        status="executed",
        result=str(generated),
    )

    response = client.get(f"/actions/{action.id}/download")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 fake handbook content"
    assert response.headers["content-type"] == "application/pdf"
