"""
MCP client for the mcp-server service, used ONLY for cancellation (undo) --
see ARCHITECTURE.md "Décision structurante n°2": the backend calls the MCP
server directly for undo, no need to re-plan through the agent.

CORRECTED after reading Hugo's mcp_instance.py / server.py: mcp-server is a
real MCP server (FastMCP, transport="streamable-http"), not a plain REST
API. It cannot be called with an arbitrary custom route like the earlier
version of this file assumed (a plain "POST /undo"). Clients must speak
the MCP protocol -- list_tools, call_tool, etc. -- via an MCP client
library. This version uses the `fastmcp` package's Client, the natural
counterpart to a server built with fastmcp.FastMCP.

The MCP endpoint is served at {MCP_SERVER_URL}/mcp by default -- that's
FastMCP's default mount path for the streamable-http transport, and
server.py doesn't override it with a `path=` argument, so the default
applies. Source: https://gofastmcp.com/deployment/running-server

RESOLVED (was "STILL OPEN, to confirm with Hugo"): no single generic
"undo" MCP tool -- docs/TOOLS.md documents one dedicated compensation
function per creation tool (close_onboarding_issue, delete_employee_record,
...), and that's what mcp-server actually implements (see
mcp_server/tools/tracker.py, mcp_server/tools/employee_db.py). This file
dispatches by `tool` to the matching compensation tool name and its single
Ref-typed argument, via _UNDO_SPEC_BY_ACTION_TOOL below. NOT YET RUN against
a real mcp-server end to end -- no PyPI/Docker access in the sandbox this
was written in; see backend/app/tests/test_mcp_client.py for what WAS
verified (the dispatch logic, with a fake fastmcp Client).
"""

from typing import Any

from fastmcp import Client

from app.config import MCP_SERVER_URL

_MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

# tool (Action.tool) -> (name of its compensation tool on mcp-server, name
# of that tool's single Ref argument -- see docs/TOOLS.md "Fonctions de
# compensation" for the full 5-row table). Add a row here each time a new
# compensation function is implemented on mcp-server; a tool missing from
# this dict raises below rather than silently doing nothing.
_UNDO_SPEC_BY_ACTION_TOOL: dict[str, tuple[str, str]] = {
    "create_onboarding_issue": ("close_onboarding_issue", "issue"),
    "create_employee_record": ("delete_employee_record", "employee"),
}


async def undo(tool: str, params: dict[str, Any], result: Any) -> dict[str, Any]:
    spec = _UNDO_SPEC_BY_ACTION_TOOL.get(tool)
    if spec is None:
        # Explicit failure rather than a silent no-op: routers/actions.py
        # wraps this call in a try/except and turns any exception into a
        # 502 (see undo_action()) -- better than marking the action
        # "undone" when nothing was actually compensated. Reachable today
        # for generate_handbook / create_calendar_event, whose compensation
        # functions (remove_handbook, remove_calendar_event) don't exist
        # yet either.
        raise RuntimeError(f"No undo compensation implemented yet for tool={tool!r}")
    undo_tool_name, result_arg_name = spec

    async with Client(_MCP_ENDPOINT) as client:
        call_result = await client.call_tool(undo_tool_name, {result_arg_name: result})

    if call_result.is_error:
        # Surface as an exception so routers/actions.py's undo_action() lets
        # it propagate as a 502, rather than silently reporting success.
        raise RuntimeError(f"mcp-server {undo_tool_name!r} tool reported an error for tool={tool!r}")

    if call_result.data is False:
        # Every compensation function returns a bool (see docs/TOOLS.md);
        # False means "nothing was actually compensated" (e.g. the employee
        # row was already gone) -- same reasoning as call_result.is_error
        # above, an explicit failure rather than a silently accepted no-op.
        raise RuntimeError(
            f"mcp-server {undo_tool_name!r} reported it could not undo tool={tool!r} (returned False)"
        )

    return {"status": "undone"}
