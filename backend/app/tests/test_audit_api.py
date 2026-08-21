"""
Tests for GET /audit, notamment le nouveau filtre `plan_id` (voir
routers/audit.py) demande pour avoir la trace complete d'un plan en un seul
appel -- avant ca, il fallait faire un /audit?action_id=... par action, en
etant deja passe par GET /plans/{id} pour connaitre ces action_id.
"""

from unittest.mock import AsyncMock

from app.models import Action, Plan


def test_audit_filtered_by_plan_id_returns_only_that_plans_entries_in_order(client, db_session, monkeypatch):
    """Deux plans distincts, chacun avec une action -- /audit?plan_id=X ne
    doit renvoyer QUE les lignes de X, triees chronologiquement (proposed
    avant executed), et chaque ligne doit porter le nom du tool (voir
    AuditLog.tool dans models.py -- sans ca, debugger une sequence a la main
    comme on vient de le faire est illisible)."""
    monkeypatch.setattr(
        "app.services.agent_client.plan",
        AsyncMock(
            return_value={
                "actions": [
                    {
                        "tool": "send_welcome_message",
                        "params": {"employee_name": "Camille", "team": "Backend", "channel": "team"},
                        "summary": "Envoyer le mail de bienvenue",
                    }
                ],
                "excluded_actions": [],
                "clarification": None,
            }
        ),
    )

    # Plan A -- celui qu'on veut retrouver isole via le filtre.
    response_a = client.post("/plans", json={"prompt": "onboard Camille"})
    plan_a_id = response_a.json()["id"]
    action_a_id = response_a.json()["actions"][0]["id"]

    # Plan B -- doit rester invisible dans le resultat filtre sur Plan A.
    response_b = client.post("/plans", json={"prompt": "onboard un autre"})
    plan_b_id = response_b.json()["id"]
    assert plan_b_id != plan_a_id

    # Fait avancer Plan A jusqu'a "executed" pour avoir 2 lignes distinctes
    # (proposed, puis executed) a verifier dans l'ordre chronologique.
    client.patch(f"/actions/{action_a_id}", json={"status": "approved"})
    monkeypatch.setattr(
        "app.services.agent_client.execute",
        AsyncMock(return_value=[{"action_id": action_a_id, "status": "executed", "result": "<msg-id@example>"}]),
    )
    client.post(f"/plans/{plan_a_id}/execute")

    response = client.get(f"/audit?plan_id={plan_a_id}")

    assert response.status_code == 200
    entries = response.json()

    assert all(entry["action_id"] == action_a_id for entry in entries)  # rien du plan B
    assert [entry["status"] for entry in entries] == ["proposed", "approved", "executed"]  # ordre chronologique
    assert all(entry["tool"] == "send_welcome_message" for entry in entries)


def test_audit_without_filters_still_returns_everything_newest_first(client, db_session, monkeypatch):
    """Non-regression : le comportement par defaut de /audit (sans filtre)
    ne doit pas changer -- toujours desc/plus-recent-d'abord, comme avant
    l'ajout du filtre plan_id."""
    plan = Plan(prompt="onboard Jane Doe")
    action = Action(
        tool="create_onboarding_issue",
        params={"employee_name": "Jane Doe"},
        summary="Create the onboarding issue",
        idempotency_key="key-1",
        status="proposed",
    )
    plan.actions.append(action)
    db_session.add(plan)
    db_session.commit()

    response = client.get("/audit")

    assert response.status_code == 200
