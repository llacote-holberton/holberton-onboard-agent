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

STILL OPEN, to confirm with Hugo before this works end to end:
mcp_instance.py currently registers zero tools (server.py's
`import tools.*` lines are commented out), so there is no "undo" tool to
call yet. This file assumes a single generic tool named "undo" that takes
{tool, params, result} and re-derives what to undo from there. If Hugo's
design ends up being one dedicated undo_<x> tool per creation tool
instead, this function's body needs to branch on `tool` and call the
matching undo_<x> tool by name -- the rest of this file (the public
`undo()` signature the backend/routers/actions.py depends on) doesn't
need to change either way.
"""

from typing import Any

from fastmcp import Client

from app.config import MCP_SERVER_URL

_MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"


async def undo(tool: str, params: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    async with Client(_MCP_ENDPOINT) as client:
        call_result = await client.call_tool(
            "undo",
            {"tool": tool, "params": params, "result": result},
        )

    if call_result.is_error:
        # Surface as an exception so routers/actions.py's undo_action() lets
        # it propagate as a 500, rather than silently reporting success.
        raise RuntimeError(f"mcp-server 'undo' tool reported an error for tool={tool!r}")

    # .data is FastMCP's fully-deserialized Python object for the tool's
    # result; expected to be a dict once the real "undo" tool exists.
    return call_result.data or {"status": "undone"}
