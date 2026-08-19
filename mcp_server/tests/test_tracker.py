"""
Unit tests for close_onboarding_issue and _extract_issue_number
(mcp_server/tools/tracker.py) -- the undo compensation for
create_onboarding_issue.

Unlike employee_db.py (pure sqlite3, no external service), this tool calls
the real GitHub API -- so the HTTP layer is mocked via httpx's own
MockTransport (already a dependency of httpx itself, no extra package
needed) rather than hitting api.github.com from a test run.

Confirmed running locally (Laurent) against the real httpx + anyio already
present alongside fastmcp -- if `@pytest.mark.anyio` errors with "no
anyio_backend fixture" or similar, anyio's pytest plugin may not be
auto-registered on this exact fastmcp/anyio version combo; the fix is
either the `anyio_backend` fixture below (already included) or, failing
that, swapping to `pytest-asyncio` (`@pytest.mark.asyncio` +
`asyncio_mode = auto` in pytest.ini) -- not expected to be needed, since
`plugins: anyio-...` already showed up unprompted in Laurent's own pytest
header from the employee_db run, meaning the plugin is active in that
environment.
"""

import httpx
import pytest

from tools import tracker

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- _extract_issue_number (pure function, no I/O) ----------------------


def test_extract_issue_number_from_html_url():
    assert tracker._extract_issue_number("https://github.com/owner/repo/issues/42") == "42"


def test_extract_issue_number_strips_trailing_slash():
    assert tracker._extract_issue_number("https://github.com/owner/repo/issues/42/") == "42"


def test_extract_issue_number_rejects_a_non_issue_url():
    with pytest.raises(ValueError):
        tracker._extract_issue_number("https://github.com/owner/repo")


# --- close_onboarding_issue (mocked GitHub call) -------------------------


_RealAsyncClient = httpx.AsyncClient
# Captured before any monkeypatching -- tracker.py's `httpx` is the exact
# same module object as this test file's `httpx` (one shared entry in
# sys.modules), so `monkeypatch.setattr(tracker.httpx, "AsyncClient", ...)`
# below replaces httpx.AsyncClient globally. Building the mock client with
# a *live* `httpx.AsyncClient` reference instead of this captured one would
# recurse into the very factory being defined.


def _client_factory(handler):
    """Swaps in an httpx.AsyncClient wired to a MockTransport instead of a
    real network connection -- close_onboarding_issue() constructs its own
    httpx.AsyncClient() internally, so this monkeypatches the class it
    resolves via `tracker.httpx.AsyncClient`."""

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    return factory


async def test_close_onboarding_issue_returns_true_when_github_confirms_closed(monkeypatch):
    monkeypatch.setattr(tracker, "GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(tracker, "GITHUB_REPO", "owner/repo")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/repos/owner/repo/issues/42"
        assert request.headers["authorization"] == "Bearer fake-token"
        return httpx.Response(200, json={"state": "closed", "number": 42})

    monkeypatch.setattr(tracker.httpx, "AsyncClient", _client_factory(handler))

    result = await tracker.close_onboarding_issue("https://github.com/owner/repo/issues/42")

    assert result is True


async def test_close_onboarding_issue_returns_false_if_github_response_is_unexpected(monkeypatch):
    monkeypatch.setattr(tracker, "GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(tracker, "GITHUB_REPO", "owner/repo")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": "open", "number": 42})

    monkeypatch.setattr(tracker.httpx, "AsyncClient", _client_factory(handler))

    result = await tracker.close_onboarding_issue("https://github.com/owner/repo/issues/42")

    assert result is False


async def test_close_onboarding_issue_raises_on_github_error_status(monkeypatch):
    monkeypatch.setattr(tracker, "GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(tracker, "GITHUB_REPO", "owner/repo")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    monkeypatch.setattr(tracker.httpx, "AsyncClient", _client_factory(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await tracker.close_onboarding_issue("https://github.com/owner/repo/issues/999")


async def test_close_onboarding_issue_requires_github_env_vars(monkeypatch):
    monkeypatch.setattr(tracker, "GITHUB_TOKEN", None)
    monkeypatch.setattr(tracker, "GITHUB_REPO", "owner/repo")

    with pytest.raises(RuntimeError):
        await tracker.close_onboarding_issue("https://github.com/owner/repo/issues/42")


async def test_close_onboarding_issue_rejects_a_non_issue_ref(monkeypatch):
    monkeypatch.setattr(tracker, "GITHUB_TOKEN", "fake-token")
    monkeypatch.setattr(tracker, "GITHUB_REPO", "owner/repo")

    with pytest.raises(ValueError):
        await tracker.close_onboarding_issue("not-a-url")
