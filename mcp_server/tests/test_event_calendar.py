"""
Unit tests for event_calendar.py's create_calendar_event. Writes a real
.ics file to disk, so these tests use tmp_path to redirect the calendar
directory without touching the real data/ directory of the project.

PORTED (2026-08-21, Laurent) from dev_laurent's mcp_server/tests/
test_event_calendar.py -- confirmed via `git diff` that this branch's
create_calendar_event has the exact same core logic (ICS generation,
default start hour, attendee handling, date/duration validation) as
dev_laurent's, which was itself originally reused from this branch. Two
adaptations were needed, not zero:
  1. The module-level directory constant is named `CALENDAR_DIR` on
     dev_laurent but `_CALENDAR_DIR` (private) here -- every reference
     below uses the name this branch actually has.
  2. The `plan_id` parameter (and its dedicated subfolder-per-plan
     behavior) doesn't exist on this branch's create_calendar_event at
     all -- the two dev_laurent tests exercising it
     (with_plan_id_writes_under_a_subfolder,
     plan_id_path_traversal_rejected) were dropped rather than adapted,
     since there's no equivalent behavior here to test. The "without
     plan_id" case is kept as-is below since it only asserts the
     (unchanged) default flat-storage behavior.
"""

from pathlib import Path

import pytest

from tools import event_calendar


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(event_calendar, "_CALENDAR_DIR", tmp_path / "calendar")


def _call(**kwargs):
    fn = event_calendar.create_calendar_event
    return (fn.fn if hasattr(fn, "fn") else fn)(**kwargs)


def _read_raw(path):
    """`newline=""` disables Python's universal-newline translation on
    read -- without it, a plain `open(path).read()` silently converts the
    file's real \\r\\n (CRLF, required for RFC 5545 interoperability) back
    to \\n, which would make the CRLF assertion below pass or fail for the
    wrong reason regardless of what create_calendar_event actually wrote
    to disk."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def test_create_calendar_event_writes_a_valid_ics_file():
    path = _call(
        title="Présentation de Léa à l'équipe",
        event_date="2026-08-25",
        duration_minutes=30,
        attendees=["Léa Martin"],
    )

    content = _read_raw(path)
    assert content.startswith("BEGIN:VCALENDAR\r\n")
    assert content.rstrip().endswith("END:VCALENDAR")
    assert "SUMMARY:Présentation de Léa à l'équipe" in content
    assert "DTSTART:20260825T090000" in content
    assert "DTEND:20260825T093000" in content


def test_create_calendar_event_default_start_hour_is_nine_am():
    path = _call(title="x", event_date="2026-01-01", duration_minutes=15, attendees=[])
    content = open(path, encoding="utf-8").read()
    assert "DTSTART:20260101T090000" in content


def test_create_calendar_event_attendee_with_at_sign_used_as_is():
    path = _call(
        title="x", event_date="2026-08-25", duration_minutes=30,
        attendees=["manager@entreprise.com"],
    )
    content = open(path, encoding="utf-8").read()
    assert "ATTENDEE;CN=manager@entreprise.com:mailto:manager@entreprise.com" in content


def test_create_calendar_event_attendee_without_at_sign_gets_a_generated_email():
    path = _call(
        title="x", event_date="2026-08-25", duration_minutes=30,
        attendees=["Léa Martin"],
    )
    content = open(path, encoding="utf-8").read()
    assert "ATTENDEE;CN=Léa Martin:mailto:léa.martin@holberton.example" in content


def test_create_calendar_event_invalid_date_raises_value_error():
    """Repro possible si le LLM fournit une date relative non résolue
    (ex: "lundi prochain" tel quel) -- ce tool n'accepte QUE l'ISO,
    contrairement à tracker.py::_resolve_start_date qui, lui, sait
    interpréter ces formulations. Ne doit jamais planter avec une
    exception Pydantic générique et peu lisible."""
    with pytest.raises(ValueError, match="non reconnue"):
        _call(title="x", event_date="lundi prochain", duration_minutes=30, attendees=[])


def test_create_calendar_event_non_positive_duration_raises_value_error():
    with pytest.raises(ValueError, match="positive"):
        _call(title="x", event_date="2026-08-25", duration_minutes=0, attendees=[])


def test_create_calendar_event_negative_duration_raises_value_error():
    with pytest.raises(ValueError, match="positive"):
        _call(title="x", event_date="2026-08-25", duration_minutes=-10, attendees=[])


def test_create_calendar_event_writes_flat_under_calendar_dir():
    """Only remaining case from dev_laurent's plan_id group -- this branch
    has no plan_id subfolder feature at all, so storage is always flat."""
    path = _call(title="x", event_date="2026-08-25", duration_minutes=30, attendees=[])

    assert Path(path).parent == event_calendar._CALENDAR_DIR
