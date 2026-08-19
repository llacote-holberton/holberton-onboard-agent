"""
Smoke-test manuel de l'outil "mailbox" expose par mcp-server, a lancer
depuis la MACHINE HOTE (pas depuis un conteneur) -- le port de mcp-server
est publie dans docker-compose.yml (HBN_MCP_PORT, 8200 par defaut), donc
il est joignable directement en localhost une fois `docker compose up`
lance.

Prerequis :
    pip install fastmcp
    (client de test jetable -- ne fait partie d'aucune dependance de service)

Usage (pile docker compose deja demarree) :
    python scripts/test_mailbox_tool.py list
    python scripts/test_mailbox_tool.py send --team Backend --channel team
    python scripts/test_mailbox_tool.py send --team Backend --channel manager
    python scripts/test_mailbox_tool.py send --team peu-importe --channel it
    python scripts/test_mailbox_tool.py send --team Inconnu --channel team   # doit echouer

Apres un "send" reussi, ouvre http://localhost:8025 (interface web MailHog,
MAILHOG_WEB_PORT dans .env) pour voir le vrai e-mail envoye : destinataires,
sujet, corps.
"""

import argparse
import asyncio
import os

from fastmcp import Client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8200")
MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"


async def list_tools():
    async with Client(MCP_ENDPOINT) as client:
        tools = await client.list_tools()

    if not tools:
        print(
            "Aucun tool expose. Verifie que server.py importe reellement les "
            "modules de tools/ (pas dans une docstring commentee -- voir le "
            "point souleve sur les imports entoures de triple guillemets)."
        )
        return

    print(f"{len(tools)} tool(s) expose(s) :")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description!r}")


async def send(employee_name: str, team: str, channel: str):
    async with Client(MCP_ENDPOINT) as client:
        try:
            result = await client.call_tool(
                "send_welcome_message",
                {"employee_name": employee_name, "team": team, "channel": channel},
            )
            print(f"OK -- Message-ID renvoye : {result.data}")
            print("Va verifier http://localhost:8025 pour voir l'e-mail reellement envoye.")
        except Exception as exc:
            # Attendu (pas un bug) si --team n'existe pas dans l'annuaire,
            # ou si le service mailhog est arrete/debranche.
            print(f"ERREUR renvoyee par l'outil : {exc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Liste les tools exposes par mcp-server (list_tools, lecture seule)")

    send_parser = subparsers.add_parser("send", help="Appelle send_welcome_message (call_tool, effet de bord reel)")
    send_parser.add_argument("--employee-name", default="Camille Test")
    send_parser.add_argument("--team", required=True, help='ex. "Backend", "Frontend", "Product" (voir employees_directory.json)')
    send_parser.add_argument("--channel", choices=["team", "manager", "it"], required=True)

    args = parser.parse_args()

    if args.command == "list":
        asyncio.run(list_tools())
    elif args.command == "send":
        asyncio.run(send(args.employee_name, args.team, args.channel))


if __name__ == "__main__":
    main()
