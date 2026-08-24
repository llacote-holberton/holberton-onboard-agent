"""
Unit tests for executor.py -- _humanize_error (pure, no MCP client needed).

CORRECTIF (2026-08-24, Laurent, portage de feature/palier5) : premier test
pour executor.py, qui n'en avait aucun sur cette branche jusqu'ici (voir
conftest.py -- même situation que mcp_server/agent avant leurs premiers
tests). Couvre uniquement _humanize_error(), la fonction pure ajoutée par
ce correctif -- pas execute_actions() dans son ensemble, qui demanderait
de mocker fastmcp.Client (hors scope de ce correctif ciblé).
"""

import executor


def test_humanize_error_strips_fastmcp_tool_prefix():
    """FastMCP préfixe systématiquement ses erreurs par "Error calling
    tool '<nom>': " -- ce préfixe technique doit disparaître, le message
    métier doit rester intact."""
    exc = Exception(
        "Error calling tool 'send_welcome_message': Équipe inconnue : "
        "'poney'. Équipes valides : ['Backend', 'Frontend']. L'action "
        "n'a pas été exécutée -- vérifiez le nom de l'équipe."
    )

    assert executor._humanize_error(exc) == (
        "Équipe inconnue : 'poney'. Équipes valides : ['Backend', "
        "'Frontend']. L'action n'a pas été exécutée -- vérifiez le nom "
        "de l'équipe."
    )


def test_humanize_error_leaves_message_unchanged_when_no_prefix():
    """Un message qui n'a pas ce préfixe (ex: une exception Python
    générique non levée par un appel d'outil FastMCP) doit ressortir
    inchangé -- le nettoyage ne doit jamais tronquer ou altérer un
    message qui ne correspond pas au motif attendu."""
    exc = ValueError("Connection refused")

    assert executor._humanize_error(exc) == "Connection refused"
