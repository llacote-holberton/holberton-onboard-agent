"""
agent has no test scaffolding yet either (same situation mcp_server was in
before tonight) -- this is the first one. planner.py does bare imports
("import planner" style, no package prefix), which only resolve when
agent/ itself (not agent/tests/) is on sys.path -- true at runtime because
Docker's CMD runs uvicorn/python from inside agent/. Pytest has no
equivalent behavior, so this conftest adds agent/ to sys.path explicitly,
once, for the whole test session (same pattern as
mcp_server/tests/conftest.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
