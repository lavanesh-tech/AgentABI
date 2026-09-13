"""Deterministic, recursive redaction of sensitive keys in recorded event
payloads (Phase 6 §9). This is a practical foundation, not a DLP
platform: a fixed, configurable set of common sensitive key names is
redacted wherever they appear, at any nesting depth, in dicts or lists.

Redaction runs *before* a payload is ever persisted or logged — no code
path stores or logs a payload prior to calling `sanitize()`, so a secret
that appeared in a tool/API payload never reaches the database or the
application log merely because it was passed through."""

from typing import Any

REDACTED_PLACEHOLDER = "***REDACTED***"

DEFAULT_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
    }
)


def sanitize(value: Any, *, sensitive_keys: frozenset[str] = DEFAULT_SENSITIVE_KEYS) -> Any:
    """Recursively redact any dict value whose key (case-insensitively)
    matches `sensitive_keys`. Never mutates `value`; returns a new
    structure. Non-container values pass through unchanged."""

    if isinstance(value, dict):
        return {
            key: (
                REDACTED_PLACEHOLDER
                if _is_sensitive(key, sensitive_keys)
                else sanitize(val, sensitive_keys=sensitive_keys)
            )
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item, sensitive_keys=sensitive_keys) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item, sensitive_keys=sensitive_keys) for item in value]
    return value


def _is_sensitive(key: str, sensitive_keys: frozenset[str]) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in sensitive_keys
