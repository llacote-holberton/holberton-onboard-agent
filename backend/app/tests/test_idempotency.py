"""
Tests for app.services.idempotency.

compute_idempotency_key is a pure function of (tool, params) -- no plan_id
involved, on purpose (see the module docstring). That is what lets the
execution endpoint recognize "this exact action was already executed under
an earlier, regenerated plan" and skip dispatching it again.
"""

from app.services.idempotency import compute_idempotency_key


def test_same_tool_and_params_produce_the_same_key():
    key1 = compute_idempotency_key("create_onboarding_issue", {"employee": "Jane Doe", "team": "eng"})
    key2 = compute_idempotency_key("create_onboarding_issue", {"employee": "Jane Doe", "team": "eng"})

    assert key1 == key2


def test_key_is_independent_of_dict_key_order():
    key1 = compute_idempotency_key("create_onboarding_issue", {"employee": "Jane Doe", "team": "eng"})
    key2 = compute_idempotency_key("create_onboarding_issue", {"team": "eng", "employee": "Jane Doe"})

    assert key1 == key2


def test_different_params_produce_different_keys():
    key1 = compute_idempotency_key("create_onboarding_issue", {"employee": "Jane Doe"})
    key2 = compute_idempotency_key("create_onboarding_issue", {"employee": "John Smith"})

    assert key1 != key2


def test_different_tools_produce_different_keys_even_with_same_params():
    params = {"employee": "Jane Doe"}
    key1 = compute_idempotency_key("create_onboarding_issue", params)
    key2 = compute_idempotency_key("send_welcome_email", params)

    assert key1 != key2


def test_key_is_a_hex_sha256_digest():
    key = compute_idempotency_key("create_onboarding_issue", {"employee": "Jane Doe"})

    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)
