from mcp_instance import mcp
import tools.tracker
import tools.employee_db
import tools.mailbox
import tools.documents
import tools.event_calendar
import resources  # noqa: F401 -- import pour effet de bord, enregistre la resource "config://allowed-tools"
import os

MCP_PORT = int(os.getenv("HBN_MCP_PORT", "8200"))

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=MCP_PORT,
        show_banner=False,
    )
