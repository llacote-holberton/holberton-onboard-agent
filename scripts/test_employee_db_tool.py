"""
Smoke-test manuel de l'outil "employee_db" expose par mcp-server, a lancer
depuis la MACHINE HOTE (pas depuis un conteneur) -- meme principe que
scripts/test_mailbox_tool.py : le port de mcp-server est publie dans
docker-compose.yml (HBN_MCP_PORT, 8200 par defaut), donc joignable en
localhost une fois `docker compose up` lance.

Contrairement a mailbox (MailHog) ou tracker (API GitHub reelle), ce tool
n'a AUCUNE dependance externe -- juste le fichier SQLite partage
(DATA_HOST_DIR/onboarding.db, ./data/onboarding.db par defaut). Donc ce
script, en plus d'appeler le tool via MCP, relit directement ce fichier
pour confirmer que la ligne est bien la -- pas besoin d'ouvrir une UI
tierce comme http://localhost:8025 pour mailbox.

Prerequis :
    pip install fastmcp
    (client de test jetable -- ne fait partie d'aucune dependance de service)

Usage (pile docker compose deja demarree) :
    python scripts/test_employee_db_tool.py create --name "Camille Test" --role "Dev Backend" --team Backend --start-date 2026-03-03
    python scripts/test_employee_db_tool.py list-rows
"""

import argparse
import asyncio
import os
import sqlite3
from pathlib import Path

from fastmcp import Client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8200")
MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

# Meme defaut que backend/app/config.py et mcp_server/tools/employee_db.py --
# si tu lances docker compose avec un DATA_HOST_DIR different, passe-le ici
# via la variable d'environnement DATA_HOST_DIR.
DB_PATH = Path(os.environ.get("DATA_HOST_DIR", "./data")).resolve() / "onboarding.db"


async def create(name: str, role: str, team: str, start_date: str):
    async with Client(MCP_ENDPOINT) as client:
        try:
            result = await client.call_tool(
                "create_employee_record",
                {"name": name, "role": role, "team": team, "start_date": start_date},
            )
            print(f"OK -- employee_id renvoye : {result.data}")
            print(f"Verifie directement dans {DB_PATH} avec :")
            print("    python scripts/test_employee_db_tool.py list-rows")
        except Exception as exc:
            print(f"ERREUR renvoyee par l'outil : {exc}")


def list_rows():
    if not DB_PATH.exists():
        print(f"Pas de fichier a {DB_PATH} -- lance d'abord 'create'.")
        return

    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            "SELECT id, name, role, team, start_date, created_at FROM employees ORDER BY created_at"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"Impossible de lire la table 'employees' ({exc}) -- lance d'abord 'create'.")
        return
    finally:
        connection.close()

    if not rows:
        print("Table 'employees' vide.")
        return

    print(f"{len(rows)} ligne(s) dans 'employees' :")
    for row in rows:
        employee_id, name, role, team, start_date, created_at = row
        print(f"  - {employee_id} | {name} | {role} | {team} | arrivee {start_date} | cree {created_at}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Appelle create_employee_record (call_tool, effet de bord reel)")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--role", required=True)
    create_parser.add_argument("--team", required=True)
    create_parser.add_argument("--start-date", required=True, help="Format ISO, ex: 2026-03-03")

    subparsers.add_parser("list-rows", help="Relit directement le fichier SQLite partage (pas d'appel MCP)")

    args = parser.parse_args()

    if args.command == "create":
        asyncio.run(create(args.name, args.role, args.team, args.start_date))
    elif args.command == "list-rows":
        list_rows()


if __name__ == "__main__":
    main()
