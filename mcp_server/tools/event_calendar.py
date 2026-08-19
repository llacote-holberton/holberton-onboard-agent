from datetime import date

from mcp_instance import mcp
from domain_types import EventRef


@mcp.tool
def create_calendar_event(
    title: str,
    event_date: date,
    duration_minutes: int,
    attendees: list[str],
) -> EventRef:
    """Crée un événement calendrier au format .ics."""
    raise NotImplementedError
