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


# --- send_welcome_message: unexpected/unused `start_date` ----------------
#
# Repro from tonight: the LLM called this tool with a `start_date` it never
# had, presumably by analogy with the other tools that do take a date.
# Pydantic/FastMCP reject unknown kwargs by default -- confirmed directly
# against real pydantic 2.13.3 (the version tonight's errors were raised
# from).
#
# CORRECTED (2026-08-20, later still): the first version of this fix used
# `**_ignored_extra_fields: Any` to absorb ANY extra field. That validated
# fine against plain pydantic in this sandbox, but crashed mcp-server at
# startup in Laurent's real environment: FastMCP explicitly rejects
# `**kwargs` on an `@mcp.tool`-decorated function ("Functions with
# **kwargs are not supported as tools", fastmcp/tools/function_parsing.py)
# -- confirmed by the real traceback, not a guess. There is no generic
# escape hatch for "accept any extra field" with FastMCP; `start_date` is
# now a named, explicitly optional, always-ignored parameter instead --
# same tests as before still apply since they only ever exercised this one
# known field, but the signature-shape test below is new: it guards
# specifically against reintroducing `**kwargs` here or on any other tool,
# since that failure mode only surfaces at mcp-server startup (import
# time), not in a unit test that merely calls the function directly.


def test_send_welcome_message_has_no_kwargs_parameter():
    """Regression guard for the real crash above -- a **kwargs-style
    parameter on an @mcp.tool function is fatal to the whole mcp-server
    process at import time, not just to this one tool, so this is worth
    locking in explicitly rather than trusting review alone to catch it
    again."""
    import inspect

    sig = inspect.signature(mailbox.send_welcome_message)
    kinds = {p.kind for p in sig.parameters.values()}
    assert inspect.Parameter.VAR_KEYWORD not in kinds


def test_send_welcome_message_ignores_an_unexpected_start_date_plain_call(monkeypatch):
    """Plain Python call: `start_date` is now a real, named, optional
    parameter -- passing it is accepted, and the value is simply unused."""
    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    message_id = mailbox.send_welcome_message(
        employee_name="Camille", team="Backend", start_date="2026-08-24"
    )

    assert isinstance(message_id, str) and message_id


def test_send_welcome_message_ignores_an_unexpected_start_date_via_validate_call(monkeypatch):
    """Same repro, but through pydantic.validate_call -- the closer proxy
    for FastMCP's own validation layer (see employee_db.py's alias tests
    for why a plain call isn't enough to prove this for the Pydantic-level
    behavior, even though it happens to also work here at the plain-Python
    level per the test above)."""
    import pydantic

    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    validated = pydantic.validate_call(mailbox.send_welcome_message)
    message_id = validated(employee_name="Camille", team="Backend", start_date="2026-08-24")

    assert isinstance(message_id, str) and message_id


def test_send_welcome_message_still_works_when_start_date_is_omitted(monkeypatch):
    """Guards against the new optional parameter accidentally becoming
    required in some form -- omitting it entirely must still work, exactly
    like before this field existed."""
    monkeypatch.setattr(mailbox.smtplib, "SMTP", _FakeSMTP)

    message_id = mailbox.send_welcome_message(employee_name="Camille", team="Backend")

    assert isinstance(message_id, str) and message_id
