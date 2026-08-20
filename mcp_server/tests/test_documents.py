"""
Unit tests for documents.py's generate_handbook -- implémentation reprise
depuis Feature/palier3 (2026-08-20, voir docstring de module côté
tools/documents.py pour l'historique). Écrit un vrai fichier HTML sur
disque (pas d'effet de bord réseau à mocker, contrairement à mailbox.py),
donc ces tests utilisent tmp_path pour rediriger DATA_DIR sans toucher au
vrai répertoire data/ du projet.
"""

from pathlib import Path

import pytest

from tools import documents


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Redirige DOCUMENTS_DIR vers un répertoire jetable pour chaque test
    -- lu au niveau module (voir la note dans documents.py), donc on
    monkeypatch directement l'attribut plutôt que la variable
    d'environnement (qui ne serait relue qu'à un rechargement du module)."""
    monkeypatch.setattr(documents, "DOCUMENTS_DIR", tmp_path / "documents")


def _call(**kwargs):
    fn = documents.generate_handbook
    return (fn.fn if hasattr(fn, "fn") else fn)(**kwargs)


def test_generate_handbook_welcome_pack_writes_html_containing_employee_id():
    path = _call(employee_id="emp-123", template="welcome_pack")

    content = open(path, encoding="utf-8").read()
    assert "emp-123" in content
    assert "<html" in content


def test_generate_handbook_mission_letter_uses_the_other_template():
    path = _call(employee_id="emp-456", template="mission_letter")

    content = open(path, encoding="utf-8").read()
    assert "emp-456" in content
    assert "Lettre de mission" in content


def test_generate_handbook_returns_a_path_string_under_documents_dir():
    path = _call(employee_id="emp-789", template="welcome_pack")

    assert isinstance(path, str)
    assert "documents" in path
    assert path.endswith(".html")


def test_generate_handbook_unknown_template_raises_value_error():
    """Garde-fou pour un cas normalement impossible via Ollama (le schéma
    JSON restreint `template` au Literal déclaré), mais atteignable par un
    appel direct (ex: /execute contourné, script de test) -- ne doit
    jamais planter silencieusement ou écrire un fichier vide."""
    with pytest.raises(ValueError, match="Gabarit inconnu"):
        _call(employee_id="emp-000", template="does_not_exist")


# --- plan_id association (RECONCILIATION 2026-08-20, Laurent) -----------


def test_generate_handbook_without_plan_id_writes_flat_under_documents_dir():
    """Comportement historique inchangé quand plan_id n'est pas fourni."""
    path = _call(employee_id="emp-111", template="welcome_pack")

    assert Path(path).parent == documents.DOCUMENTS_DIR


def test_generate_handbook_with_plan_id_writes_under_a_subfolder():
    path = _call(employee_id="emp-222", template="welcome_pack", plan_id="plan-abc")

    assert Path(path).parent == documents.DOCUMENTS_DIR / "plan-abc"
    assert Path(path).is_file()


def test_generate_handbook_two_plans_do_not_collide():
    path_a = _call(employee_id="emp-333", template="welcome_pack", plan_id="plan-a")
    path_b = _call(employee_id="emp-333", template="welcome_pack", plan_id="plan-b")

    assert path_a != path_b
    assert Path(path_a).is_file()
    assert Path(path_b).is_file()


def test_generate_handbook_plan_id_path_traversal_rejected():
    with pytest.raises(ValueError, match="plan_id invalide"):
        _call(employee_id="emp-444", template="welcome_pack", plan_id="../../etc")
