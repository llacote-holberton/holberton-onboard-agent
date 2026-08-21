"""
Unit tests for mailbox.py -- _resolve_recipients (pure, reads the real
fixture directory) and send_welcome_message's team/channel routing. SMTP
itself is mocked (monkeypatching mailbox.smtplib.SMTP) so no real MailHog
connection is needed.

PORTED (2026-08-21, Laurent) from dev_laurent's mcp_server/tests/
test_mailbox.py -- Feature/palier3's mailbox.py implements the exact same
_resolve_recipients()/send_welcome_message() core logic (byte-identical
function bodies, confirmed via `git diff`), so those tests port as-is.
Three groups of tests from the original file were dropped, not adapted,
because they exercise behavior this branch's send_welcome_message simply
doesn't have:
  - `channel` has NO default here (it's a required positional arg on this
    branch, unlike dev_laurent's `= "team"` default added later) -- every
    call below passes `channel=` explicitly instead of relying on a
    default.
  - `start_date` doesn't exist as a parameter at all on this branch (it
    was added on dev_laurent specifically to absorb a hallucinated LLM
    field) -- calling with `start_date=...` here would raise TypeError,
    so those tests were left out rather than force-adapted.
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


# --- send_welcome_message: team/channel routing ---------------------------


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


def test_send_welcome_message_team_channel_sends_to_all_members(monkeypatch):
    """Adapted from dev_laurent's "defaults_channel_to_team_when_omitted"
    -- channel has no default on this branch, so it's passed explicitly
    instead of relying on one."""
    monkeypatch.setattr(mailbox, "smtplib", mailbox.smtplib)
    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    message_id = mailbox.send_welcome_message(employee_name="Camille", team="Backend", channel="team")

    assert isinstance(message_id, str) and message_id
    assert set(_FakeSMTP.last_call["recipients"]) == {
        "sofia.martins@holberton.example",
        "karim.haddad@holberton.example",
        "lea.fontaine@holberton.example",
    }


def test_send_welcome_message_channel_manager_routes_to_manager_only(monkeypatch):
    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    mailbox.send_welcome_message(employee_name="Camille", team="Backend", channel="manager")

    assert _FakeSMTP.last_call["recipients"] == ["sofia.martins@holberton.example"]


def test_send_welcome_message_still_raises_for_an_unknown_team(monkeypatch):
    """An unknown `team` must keep failing loudly (see mailbox.py's own
    module docstring: never invent a recipient address)."""
    import pytest

    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    with pytest.raises(ValueError):
        mailbox.send_welcome_message(employee_name="Camille", team="Inconnu", channel="team")


def test_send_welcome_message_has_no_kwargs_parameter():
    """Regression guard: a **kwargs-style parameter on an @mcp.tool
    function is fatal to the whole mcp-server process at import time (see
    fastmcp's from_function() validation), not just to this one tool."""
    import inspect

    sig = inspect.signature(mailbox.send_welcome_message)
    kinds = {p.kind for p in sig.parameters.values()}
    assert inspect.Parameter.VAR_KEYWORD not in kinds
