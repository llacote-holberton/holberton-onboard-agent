"""
Unit tests for event_calendar.py's create_calendar_event -- implémentation
reprise depuis Feature/palier3 (2026-08-20, voir docstring de module côté
tools/event_calendar.py). Écrit un vrai fichier .ics sur disque, donc ces
tests utilisent tmp_path pour rediriger DATA_DIR sans toucher au vrai
répertoire data/ du projet -- même pattern que test_documents.py.
"""

import pytest

from tools import event_calendar


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(event_calendar, "CALENDAR_DIR", tmp_path / "calendar")


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
