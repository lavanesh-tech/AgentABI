"""Phase 15 spec §33 security/redaction tests for `app.observability.
redaction`. Pure stdlib-only module — no `pytest`/`structlog`/pydantic
needed to exercise it, but this sandbox has neither `pytest` nor any
project dependency installed at all this session (confirmed: `pip
install opentelemetry-api` returns "No matching distribution found" —
PyPI itself is unreachable here, same restriction as every prior phase).
Written and `py_compile`-clean; not pytest-executed. See docs/DECISIONS.md.
"""

from app.observability.redaction import is_sensitive_key, safe_attributes


def test_blocks_known_secret_fields():
    blocked = {
        "authorization": "Bearer xyz",
        "access_token": "abc",
        "OPENAI_API_KEY": "sk-xxx",
        "github_client_secret": "shh",
        "GITHUB_WEBHOOK_SECRET": "shh",
        "jwt_secret": "shh",
        "Cookie": "session=abc",
    }
    result = safe_attributes(blocked)
    assert result == {}


def test_keeps_safe_scalar_attributes():
    result = safe_attributes(
        {"agentabi.project_id": "p1", "agentabi.retry_count": 2, "agentabi.hard_block": True}
    )
    assert result == {
        "agentabi.project_id": "p1",
        "agentabi.retry_count": 2,
        "agentabi.hard_block": True,
    }


def test_drops_none_values():
    assert safe_attributes({"agentabi.optional": None}) == {}


def test_truncates_long_string_values():
    long_value = "x" * 1000
    result = safe_attributes({"agentabi.evidence_summary": long_value})
    assert len(result["agentabi.evidence_summary"]) < len(long_value)
    assert result["agentabi.evidence_summary"].endswith("...(truncated)")


def test_non_primitive_values_become_type_names_not_raw_dumps():
    result = safe_attributes({"agentabi.payload": {"secret_looking_key": "value"}})
    assert result["agentabi.payload"] == "dict"


def test_is_sensitive_key_case_insensitive_and_substring_match():
    assert is_sensitive_key("Authorization")
    assert is_sensitive_key("x-api-key")
    assert is_sensitive_key("github_oauth_client_secret")
    assert not is_sensitive_key("agentabi.project_id")
