"""
Tool exploratoire en lecture seule : liste les équipes valides de
l'annuaire interne (même fixture que mailbox.py et employee_db.py --
source de vérité unique). Utilisé par le planificateur (agent/planner.py)
pour permettre à l'agent de vérifier une équipe AVANT de proposer une
action, plutôt que de découvrir l'erreur seulement à l'exécution.

Aucun effet de bord : sert de base à la boucle d'itération du palier 4
("l'agent enchaîne plusieurs tours d'outils avant de répondre").
"""

import json
from pathlib import Path

from mcp_instance import mcp

_DIRECTORY_PATH = Path(__file__).parent / "fixtures" / "employees_directory.json"


@mcp.tool
def list_teams() -> list[str]:
    """Liste les noms d'équipes valides de l'annuaire interne. À utiliser
    pour vérifier qu'une équipe existe avant de créer une fiche employé ou
    d'envoyer un message -- lecture seule, aucun effet de bord."""
    with open(_DIRECTORY_PATH, encoding="utf-8") as f:
        directory = json.load(f)["departments"]
    return sorted(directory.keys())
