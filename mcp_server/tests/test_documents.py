"""
Unit tests for documents.py's generate_handbook. Writes a real HTML file
to disk (no network side effect to mock, unlike mailbox.py), so these
tests use tmp_path to redirect the documents directory without touching
the real data/ directory of the project.

PORTED (2026-08-21, Laurent) from dev_laurent's mcp_server/tests/
test_documents.py -- confirmed via `git diff` that this branch's
generate_handbook has the exact same core logic (template rendering,
unknown-template rejection) as dev_laurent's, which was itself originally
reused from this branch. Two adaptations were needed, not zero:
  1. The module-level directory constant is named `DOCUMENTS_DIR` on
     dev_laurent but `_DOCUMENTS_DIR` (private) here -- every reference
     below uses the name this branch actually has.
  2. The `plan_id` parameter (and its dedicated subfolder-per-plan
     behavior) doesn't exist on this branch's generate_handbook at all --
     the three dev_laurent tests exercising it
     (with_plan_id_writes_under_a_subfolder, two_plans_do_not_collide,
     plan_id_path_traversal_rejected) were dropped rather than adapted,
     since there's no equivalent behavior here to test. The "without
     plan_id" case is kept as-is below since it only asserts the
     (unchanged) default flat-storage behavior.
"""

from pathlib import Path

import pytest

from tools import documents


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Redirige _DOCUMENTS_DIR vers un répertoire jetable pour chaque test
    -- lu au niveau module, donc on monkeypatch directement l'attribut
    plutôt que la variable d'environnement (qui ne serait relue qu'à un
    rechargement du module)."""
    monkeypatch.setattr(documents, "_DOCUMENTS_DIR", tmp_path / "documents")


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
    """Garde-fou pour un cas normalement impossible via le LLM (le schéma
    JSON restreint `template` au Literal déclaré), mais atteignable par un
    appel direct (ex: /execute contourné, script de test) -- ne doit
    jamais planter silencieusement ou écrire un fichier vide."""
    with pytest.raises(ValueError, match="Gabarit inconnu"):
        _call(employee_id="emp-000", template="does_not_exist")


def test_generate_handbook_writes_flat_under_documents_dir():
    """Only remaining case from dev_laurent's plan_id group -- this branch
    has no plan_id subfolder feature at all, so storage is always flat."""
    path = _call(employee_id="emp-111", template="welcome_pack")

    assert Path(path).parent == documents._DOCUMENTS_DIR
