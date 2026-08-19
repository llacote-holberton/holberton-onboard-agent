from datetime import date

from mcp_instance import mcp
from domain_types import EmployeeRef


@mcp.tool
def create_employee_record(
    name: str,
    role: str,
    team: str,
    start_date: date,
) -> EmployeeRef:
    """Écrit la fiche du nouveau collaborateur en base."""
    raise NotImplementedError
