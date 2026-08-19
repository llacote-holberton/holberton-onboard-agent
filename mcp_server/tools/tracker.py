from datetime import date

from mcp_instance import mcp
from domain_types import IssueRef


@mcp.tool
def create_onboarding_issue(
    employee_name: str,
    start_date: date,
    checklist: list[str],
) -> IssueRef:
    """Crée un ticket/epic d'onboarding sur le tracker (GitHub Issues)."""
    raise NotImplementedError
