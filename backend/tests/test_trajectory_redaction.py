"""Pure unit tests for `app/trajectory/redaction.py`. No database, no
I/O. Uses only fake test values (Phase 6 §29)."""

from app.trajectory.redaction import REDACTED_PLACEHOLDER, sanitize


def test_top_level_sensitive_key_is_redacted():
    result = sanitize({"password": "hunter2", "username": "alice"})
    assert result["password"] == REDACTED_PLACEHOLDER
    assert result["username"] == "alice"


def test_nested_dict_is_redacted():
    result = sanitize({"customer_id": "991", "nested": {"api_key": "secret-value"}})
    assert result["customer_id"] == "991"
    assert result["nested"]["api_key"] == REDACTED_PLACEHOLDER


def test_deeply_nested_and_list_redaction():
    payload = {
        "outer": [
            {"token": "abc"},
            {"safe": "value", "nested": {"refresh_token": "xyz"}},
        ]
    }
    result = sanitize(payload)
    assert result["outer"][0]["token"] == REDACTED_PLACEHOLDER
    assert result["outer"][1]["safe"] == "value"
    assert result["outer"][1]["nested"]["refresh_token"] == REDACTED_PLACEHOLDER


def test_secret_acceptance_case_from_phase_6_spec():
    """Exact payload from the Phase 6 spec §29 (fake values only)."""

    payload = {
        "customer_id": "991",
        "authorization": "Bearer very-secret-token",
        "nested": {"api_key": "secret-value"},
    }
    result = sanitize(payload)
    assert result["customer_id"] == "991"
    assert result["authorization"] == REDACTED_PLACEHOLDER
    assert result["nested"]["api_key"] == REDACTED_PLACEHOLDER
    # The original secrets must not appear anywhere in the result.
    assert "very-secret-token" not in str(result)
    assert "secret-value" not in str(result)


def test_case_insensitive_and_hyphenated_key_matching():
    result = sanitize({"API-Key": "x", "AUTHORIZATION": "y"})
    assert result["API-Key"] == REDACTED_PLACEHOLDER
    assert result["AUTHORIZATION"] == REDACTED_PLACEHOLDER


def test_non_sensitive_keys_and_scalars_pass_through_unchanged():
    assert sanitize({"amount": 125.0, "currency": "USD"}) == {"amount": 125.0, "currency": "USD"}
    assert sanitize(None) is None
    assert sanitize(42) == 42
    assert sanitize("plain string") == "plain string"


def test_does_not_mutate_input():
    original = {"nested": {"secret": "x"}}
    sanitize(original)
    assert original["nested"]["secret"] == "x"


def test_sanitize_is_deterministic():
    payload = {"a": 1, "nested": {"token": "t", "b": [1, 2, {"password": "p"}]}}
    assert sanitize(payload) == sanitize(payload)
