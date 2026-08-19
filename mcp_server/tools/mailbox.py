from typing import Literal

from mcp_instance import mcp
from domain_types import MessageRef


@mcp.tool
def send_welcome_message(
    recipient: str,
    employee_name: str,
    channel: Literal["team", "manager", "it"],
) -> MessageRef:
    """Envoie un message d'accueil (mailbox locale simulée / MailHog)."""
    raise NotImplementedError