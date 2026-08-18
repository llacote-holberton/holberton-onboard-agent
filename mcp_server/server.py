from mcp_instance import mcp

"""
import tools.tracker
import tools.employee_db
import tools.mailbox
import tools.documents
import tools.calendar
"""
import os


MCP_PORT = int(os.getenv("HBN_MCP_PORT", "5003"))

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=MCP_PORT,
        show_banner=False,
    )
