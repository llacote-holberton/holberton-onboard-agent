from typing import Literal

from mcp_instance import mcp
from domain_types import DocumentRef


@mcp.tool
def generate_handbook(
    employee_id: str,
    template: Literal["welcome_pack", "mission_letter"],
) -> DocumentRef:
    """Génère un document PDF depuis un gabarit HTML (Jinja2 + WeasyPrint)."""
    raise NotImplementedError
