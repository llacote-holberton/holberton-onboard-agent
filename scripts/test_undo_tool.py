"""
Smoke-test manuel des DEUX fonctions de compensation ("undo") implementees
ce soir (2026-08-20) : close_onboarding_issue et delete_employee_record.
Meme principe que scripts/test_mailbox_tool.py et
scripts/test_employee_db_tool.py -- a lancer depuis la MACHINE HOTE, pile
docker compose deja demarree.

Ce script parle DIRECTEMENT au serveur MCP (comme les deux precedents), pas
au backend -- il ne passe donc PAS par POST /actions/{id}/undo ni par
backend/app/services/mcp_client.py::undo(). C'est volontaire : ca isole
"est-ce que la fonction de compensation elle-meme marche" de "est-ce que le
dispatch backend -> mcp-server marche" (ce dernier n'est verifie que par
test_mcp_client.py, avec un fastmcp.Client factice -- voir docs/TESTING.md
"Known gaps"). Si ce script passe mais que POST /actions/{id}/undo echoue
via le frontend, le probleme est cote backend (mcp_client.py), pas cote
mcp-server.

Prerequis :
    pip install fastmcp

Usage :
    # Issue GitHub : cree puis ferme immediatement (verifie tout le cycle)
    python scripts/test_undo_tool.py create-and-close-issue --employee-name "Camille Test" --start-date 2026-03-03

    # Ferme une issue existante (deja creee par ailleurs)
    python scripts/test_undo_tool.py close-issue --issue-url https://github.com/owner/repo/issues/42

    # Fiche employe : cree puis supprime immediatement
    python scripts/test_undo_tool.py create-and-delete-employee --name "Camille Test" --role "Dev Backend" --team Backend --start-date 2026-03-03

    # Supprime une fiche existante (deja creee par ailleurs)
    python scripts/test_undo_tool.py delete-employee --employee-id <id>

Apres un "close-issue" reussi, verifie sur GitHub que l'issue est bien
fermee (etat visible directement sur la page de l'issue). Apres un
"delete-employee", verifie avec :
    python scripts/test_employee_db_tool.py list-rows
"""

import argparse
import asyncio
import os

from fastmcp import Client

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8200")
MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"


async def close_issue(issue_url: str):
    async with Client(MCP_ENDPOINT) as client:
        try:
            result = await client.call_tool("close_onboarding_issue", {"issue": issue_url})
            print(f"OK -- closed={result.data} pour {issue_url}")
            if result.data is not True:
                print("ATTENTION : la fonction a repondu sans exception mais n'a pas confirme la fermeture (data != True).")
        except Exception as exc:
            print(f"ERREUR renvoyee par l'outil : {exc}")


async def create_and_close_issue(employee_name: str, start_date: str):
    async with Client(MCP_ENDPOINT) as client:
        try:
            created = await client.call_tool(
                "create_onboarding_issue",
                {"employee_name": employee_name, "start_date": start_date},
            )
        except Exception as exc:
            print(f"ERREUR a la creation de l'issue : {exc}")
            return
        issue_url = created.data
        print(f"Issue creee : {issue_url}")

        try:
            closed = await client.call_tool("close_onboarding_issue", {"issue": issue_url})
            print(f"OK -- closed={closed.data}")
        except Exception as exc:
            print(f"ERREUR a la fermeture de l'issue : {exc}")


async def delete_employee(employee_id: str):
    async with Client(MCP_ENDPOINT) as client:
        try:
            result = await client.call_tool("delete_employee_record", {"employee": employee_id})
            print(f"OK -- deleted={result.data} pour {employee_id}")
            if result.data is not True:
                print("ATTENTION : aucune ligne supprimee (id inconnu, ou deja supprimee).")
        except Exception as exc:
            print(f"ERREUR renvoyee par l'outil : {exc}")


async def create_and_delete_employee(name: str, role: str, team: str, start_date: str):
    async with Client(MCP_ENDPOINT) as client:
        try:
            created = await client.call_tool(
                "create_employee_record",
                {"name": name, "role": role, "team": team, "start_date": start_date},
            )
        except Exception as exc:
            print(f"ERREUR a la creation de la fiche : {exc}")
            return
        employee_id = created.data
        print(f"Fiche creee : {employee_id}")

        try:
            deleted = await client.call_tool("delete_employee_record", {"employee": employee_id})
            print(f"OK -- deleted={deleted.data}")
        except Exception as exc:
            print(f"ERREUR a la suppression de la fiche : {exc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("close-issue", help="Ferme une issue GitHub existante")
    p.add_argument("--issue-url", required=True, help="URL complete renvoyee par create_onboarding_issue")

    p = subparsers.add_parser("create-and-close-issue", help="Cree une issue puis la ferme immediatement")
    p.add_argument("--employee-name", default="Camille Test")
    p.add_argument("--start-date", required=True, help="Format ISO, ex: 2026-03-03")

    p = subparsers.add_parser("delete-employee", help="Supprime une fiche employe existante")
    p.add_argument("--employee-id", required=True)

    p = subparsers.add_parser("create-and-delete-employee", help="Cree une fiche puis la supprime immediatement")
    p.add_argument("--name", default="Camille Test")
    p.add_argument("--role", default="Dev Backend")
    p.add_argument("--team", default="Backend")
    p.add_argument("--start-date", required=True, help="Format ISO, ex: 2026-03-03")

    args = parser.parse_args()

    if args.command == "close-issue":
        asyncio.run(close_issue(args.issue_url))
    elif args.command == "create-and-close-issue":
        asyncio.run(create_and_close_issue(args.employee_name, args.start_date))
    elif args.command == "delete-employee":
        asyncio.run(delete_employee(args.employee_id))
    elif args.command == "create-and-delete-employee":
        asyncio.run(create_and_delete_employee(args.name, args.role, args.team, args.start_date))


if __name__ == "__main__":
    main()
