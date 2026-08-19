"""
Unit tests for app.services.mcp_client.undo() -- the dispatch logic that
replaced the earlier single generic "undo" MCP tool call (see that
module's docstring). `fastmcp.Client` itself is faked here (a tiny
in-process stand-in, not a real MCP round trip) so these tests run without
mcp-server, matching how test_actions_api.py already mocks
`app.services.mcp_client.undo` at the boundary one layer up -- this file
is what actually exercises the dispatch table those higher-level tests
don't touch.

Actually run (not just written blind) in the sandbox this was authored in,
outside this file's normal location: app.services.mcp_client and
app.config import neither fastapi nor sqlalchemy, so this file was
temporarily copied next to a plain `backend/` on PYTHONPATH (bypassing
tests/conftest.py, which does import fastapi -- not installable here, no
PyPI access) and run standalone. All 5 pass. What that run does NOT cover:
the real `fastmcp.Client`'s actual async interface (whether `call_tool()`
truly returns an object with `.data`/`.is_error` attributes shaped like
`_FakeCallResult` below) -- that part is the same kind of assumption the
employee_db.py `.fn` note had, which did turn out wrong; if it's wrong
here too, pytest will point at the exact line, same as before.
"""

import pytest

from app.services import mcp_client

# Every test function below is `async def` (undo() itself is async) --
# needs an async-capable pytest runner. Same anyio-marker pattern as
# mcp_server/tests/test_tracker.py; see that file's docstring for the
# fallback if anyio's pytest plugin isn't auto-registered here (fastmcp
# pulls in anyio transitively, same as it does for mcp_server, so this is
# expected to just work, but wasn't run in this sandbox -- see module
# docstring above).
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeCallResult:
    def __init__(self, data=None, is_error=False):
        self.data = data
        self.is_error = is_error


class _FakeMcpClient:
    """Stand-in for fastmcp.Client: records every call_tool() invocation
    and returns a fixed, test-supplied result."""

    def __init__(self, url, *, response=None, calls=None):
        self.response = response
        self.calls = calls if calls is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def call_tool(self, name, params):
        self.calls.append((name, params))
        return self.response


def _patch_client(monkeypatch, response):
    calls = []
    monkeypatch.setattr(
        mcp_client, "Client", lambda url: _FakeMcpClient(url, response=response, calls=calls)
    )
    return calls


async def test_undo_dispatches_create_onboarding_issue_to_close_onboarding_issue(monkeypatch):
    calls = _patch_client(monkeypatch, _FakeCallResult(data=True))

    outcome = await mcp_client.undo(
        "create_onboarding_issue", {"employee_name": "Jane"}, "https://github.com/o/r/issues/42"
    )

    assert outcome == {"status": "undone"}
    assert calls == [("close_onboarding_issue", {"issue": "https://github.com/o/r/issues/42"})]


async def test_undo_dispatches_create_employee_record_to_delete_employee_record(monkeypatch):
    calls = _patch_client(monkeypatch, _FakeCallResult(data=True))

    outcome = await mcp_client.undo("create_employee_record", {"name": "Jane"}, "emp-id-1")

    assert outcome == {"status": "undone"}
    assert calls == [("delete_employee_record", {"employee": "emp-id-1"})]


async def test_undo_raises_for_a_tool_with_no_compensation_implemented_yet(monkeypatch):
    def _unexpected_client(url):
        raise AssertionError("Client should never be constructed for an unmapped tool")

    monkeypatch.setattr(mcp_client, "Client", _unexpected_client)

    with pytest.raises(RuntimeError):
        await mcp_client.undo("generate_handbook", {}, "/data/documents/handbook.pdf")


async def test_undo_raises_when_mcp_server_reports_an_error(monkeypatch):
    _patch_client(monkeypatch, _FakeCallResult(is_error=True))

    with pytest.raises(RuntimeError):
        await mcp_client.undo("create_onboarding_issue", {}, "https://github.com/o/r/issues/42")


async def test_undo_raises_when_compensation_function_returns_false(monkeypatch):
    """False means "nothing was actually compensated" (see docs/TOOLS.md
    and mcp_client.py's own comment on this branch) -- treated as a
    failure, not a silent success."""
    _patch_client(monkeypatch, _FakeCallResult(data=False))

    with pytest.raises(RuntimeError):
        await mcp_client.undo("create_employee_record", {}, "does-not-exist")
