"""
Unit tests for mailbox.py -- _resolve_recipients (pure, reads the real
fixture directory) and send_welcome_message's new default for `channel`
(added 2026-08-20 after a real run omitted it entirely: "Missing required
argument"). SMTP itself is mocked (monkeypatching mailbox.smtplib.SMTP) so
no real MailHog connection is needed.
"""

from tools import mailbox


# --- _resolve_recipients (pure function, real fixture file) --------------


def test_resolve_recipients_team_channel_returns_all_members():
    recipients = mailbox._resolve_recipients("Backend", "team")
    assert set(recipients) == {
        "sofia.martins@holberton.example",
        "karim.haddad@holberton.example",
        "lea.fontaine@holberton.example",
    }


def test_resolve_recipients_manager_channel_returns_manager_only():
    recipients = mailbox._resolve_recipients("Backend", "manager")
    assert recipients == ["sofia.martins@holberton.example"]


def test_resolve_recipients_it_channel_ignores_team():
    recipients = mailbox._resolve_recipients("this-team-does-not-exist", "it")
    assert recipients == ["it-support@holberton.example"]


def test_resolve_recipients_unknown_department_raises():
    import pytest

    with pytest.raises(ValueError):
        mailbox._resolve_recipients("Inconnu", "team")


# --- send_welcome_message: default `channel` ------------------------------


class _FakeSMTP:
    """Stand-in for smtplib.SMTP -- records the one sendmail() call instead
    of opening a real connection to MailHog."""

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def sendmail(self, sender, recipients, message):
        self.__class__.last_call = {"sender": sender, "recipients": recipients, "message": message}


def test_send_welcome_message_defaults_channel_to_team_when_omitted(monkeypatch):
    """The exact repro from tonight: the LLM called this tool with
    employee_name + team but no channel at all. A plain Python call (like
    below) already honors the new `= "team"` default -- unlike the
    validation_alias case in employee_db.py, no Pydantic validation layer
    is needed to exercise this, since default parameter values are a plain
    Python function feature."""
    monkeypatch.setattr(mailbox, "smtplib", mailbox.smtplib)
    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    message_id = mailbox.send_welcome_message(employee_name="Camille", team="Backend")

    assert isinstance(message_id, str) and message_id
    assert set(_FakeSMTP.last_call["recipients"]) == {
        "sofia.martins@holberton.example",
        "karim.haddad@holberton.example",
        "lea.fontaine@holberton.example",
    }


def test_send_welcome_message_channel_is_still_overridable(monkeypatch):
    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    mailbox.send_welcome_message(employee_name="Camille", team="Backend", channel="manager")

    assert _FakeSMTP.last_call["recipients"] == ["sofia.martins@holberton.example"]


def test_send_welcome_message_still_raises_for_an_unknown_team(monkeypatch):
    """The default only covers the omitted-`channel` case -- an unknown
    `team` must keep failing loudly (see mailbox.py's own module
    docstring: never invent a recipient address)."""
    import pytest

    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    with pytest.raises(ValueError):
        mailbox.send_welcome_message(employee_name="Camille", team="Inconnu")
