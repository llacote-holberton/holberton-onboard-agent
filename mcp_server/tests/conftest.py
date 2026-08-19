"""
mcp_server has no test scaffolding yet (unlike backend/app/tests/, which
already has its own conftest.py + pytest.ini) -- this is the first one.

server.py and every module under tools/ do bare imports ("from mcp_instance
import mcp", "from domain_types import ..."), which only resolve when
mcp_server/ itself (not mcp_server/tests/) is on sys.path -- true at
runtime because Docker's WORKDIR/CMD run `python server.py` from inside
mcp_server/, which puts that directory on sys.path[0] automatically. Pytest
has no equivalent behavior, so this conftest adds mcp_server/ to sys.path
explicitly, once, for the whole test session.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
