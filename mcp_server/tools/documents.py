"""
Implémentation réelle du tool "documents" : génère un document d'accueil
au format HTML à partir d'un gabarit Jinja2 embarqué. Fallback HTML
assumé (voir SPEC.md "hors-scope") plutôt qu'une conversion PDF via
WeasyPrint -- choix de fiabilité pour rester dans le budget restant
avant le checkpoint, évite une dépendance système supplémentaire à
risque (Pango/Cairo) à ce stade avancé du hackathon.

Écrit sous DATA_DIR/documents/ et retourne le chemin du fichier comme
DocumentRef.

RÉCONCILIATION (2026-08-20, Laurent) : implémentation reprise telle quelle
depuis Feature/palier3 (Hugo) -- dev_laurent n'avait qu'un stub
(`raise NotImplementedError`) pour ce tool. Seul changement : DATA_DIR
aligné sur la convention établie par employee_db.py (`./data` résolu en
absolu, pas `/app/data` en dur) -- sans effet en Docker, où
docker-compose.yml fixe explicitement DATA_DIR=/app/data, mais nécessaire
pour que les scripts autonomes (scripts/test_*.py) et les tests unitaires
fonctionnent aussi hors conteneur.

RÉCONCILIATION 2026-08-20 (Laurent) -- association plan_id : le fichier
généré est maintenant rangé sous DOCUMENTS_DIR/<plan_id>/ quand un plan_id
est fourni (sinon comportement inchangé, à plat sous DOCUMENTS_DIR), pour
pouvoir retrouver/télécharger les fichiers d'un plan donné depuis le
frontend (voir backend/app/routers/actions.py::download_action_file).
Le paramètre `plan_id` est décrit au LLM comme réservé au système -- le
backend écrase toujours la valeur avant dispatch réel (voir
backend/app/routers/plans.py::execute_plan(), même principe que la
validation d'équipe côté agent/planner.py::_flag_unknown_teams : ne
jamais faire confiance au LLM pour une valeur critique pour la
correction).
"""

import os
from pathlib import Path
from typing import Annotated, Literal

from jinja2 import Template
from pydantic import Field

from mcp_instance import mcp
from domain_types import DocumentRef

# Même convention que employee_db.py::DATA_DIR -- lu au niveau module (pas
# capturé dans une fermeture) pour que les tests puissent le monkeypatcher
# sans recharger le module.
DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
DOCUMENTS_DIR = DATA_DIR / "documents"


def _resolve_target_dir(plan_id: str | None) -> Path:
    """Sans plan_id : comportement historique, à plat sous DOCUMENTS_DIR.
    Avec plan_id : sous-dossier dédié, pour que les fichiers de plans
    différents ne se mélangent/écrasent jamais et puissent être retrouvés
    un par un. Rejette toute tentative de path traversal (un plan_id ne
    devrait normalement jamais contenir '/' ou '..', mais le backend
    écrase cette valeur de toute façon -- garde-fou en profondeur, pas la
    seule ligne de défense)."""
    if not plan_id:
        return DOCUMENTS_DIR
    if "/" in plan_id or "\\" in plan_id or ".." in plan_id:
        raise ValueError(f"plan_id invalide : '{plan_id}'.")
    return DOCUMENTS_DIR / plan_id

_TEMPLATES = {
    "welcome_pack": Template("""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>Livret d'accueil</title></head>
<body>
  <h1>Bienvenue !</h1>
  <p>Ce livret d'accueil a été généré pour le collaborateur
     d'identifiant <strong>{{ employee_id }}</strong>.</p>
  <h2>Au programme de votre arrivée</h2>
  <ul>
    <li>Présentation de l'équipe</li>
    <li>Accès aux outils internes</li>
    <li>Premiers contacts utiles</li>
  </ul>
</body>
</html>
"""),
    "mission_letter": Template("""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>Lettre de mission</title></head>
<body>
  <h1>Lettre de mission</h1>
  <p>Ce document concerne le collaborateur d'identifiant
     <strong>{{ employee_id }}</strong>.</p>
  <p>Merci de compléter les objectifs et responsabilités du poste
     avant remise au collaborateur.</p>
</body>
</html>
"""),
}


@mcp.tool
def generate_handbook(
    employee_id: Annotated[
        str,
        Field(description="Identifiant de la fiche employé, retourné par create_employee_record."),
    ],
    template: Annotated[
        Literal["welcome_pack", "mission_letter"],
        Field(
            description=(
                "Gabarit à utiliser : 'welcome_pack' pour un livret "
                "d'accueil général (par défaut pour un onboarding "
                "standard), 'mission_letter' pour une lettre de mission "
                "détaillant les objectifs du poste."
            )
        ),
    ],
    plan_id: Annotated[
        str | None,
        Field(
            description=(
                "Réservé au système -- NE JAMAIS renseigner ce champ "
                "toi-même, la valeur que tu fournirais serait de toute "
                "façon ignorée et remplacée."
            )
        ),
    ] = None,
) -> DocumentRef:
    """Génère un document d'accueil (HTML) à partir d'un gabarit, pour le
    nouveau collaborateur identifié par employee_id. Nécessite que la
    fiche employé ait déjà été créée (voir create_employee_record).
    Retourne le chemin du fichier généré (DocumentRef, alias de str).

    Note : le nom de la fonction ("handbook") et sa docstring d'origine
    mentionnaient un PDF -- ce n'est PAS ce que fait cette implémentation
    (HTML brut, voir docstring de module pour le choix assumé). Le nom du
    tool reste inchangé pour ne pas casser le contrat déjà connu du LLM
    (system prompt, _SUMMARY_TEMPLATES côté agent/planner.py)."""
    tpl = _TEMPLATES.get(template)
    if tpl is None:
        raise ValueError(
            f"Gabarit inconnu : '{template}'. Gabarits valides : {sorted(_TEMPLATES)}."
        )

    target_dir = _resolve_target_dir(plan_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{template}_{employee_id}.html"
    filepath = target_dir / filename

    html = tpl.render(employee_id=employee_id)
    filepath.write_text(html, encoding="utf-8")

    return str(filepath)
