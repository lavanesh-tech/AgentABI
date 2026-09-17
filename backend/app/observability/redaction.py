"""Attribute redaction (Phase 15 spec §9/§19/§33). The single source of
truth for what is safe to attach to a span or log line — every span
helper in this package routes attributes through `safe_attributes`
rather than setting them directly.
"""

from typing import Any

# Substring match, case-insensitive — deliberately broad rather than an
# exact-key allowlist, so a differently-cased or prefixed variant (e.g.
# `github_client_secret`, `Authorization`, `x-api-key`) is still caught.
_BLOCKED_SUBSTRINGS = (
    "authorization",
    "access_token",
    "accesstoken",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "openai_api_key",
    "github_client_secret",
    "github_oauth_client_secret",
    "github_webhook_secret",
    "jwt_secret",
    "jwt",
    "password",
    "secret",
    "token",
    "credential",
    "cookie",
    "authorization_header",
)

_MAX_VALUE_LENGTH = 512


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _BLOCKED_SUBSTRINGS)


def safe_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Drops sensitive keys entirely (never a redacted placeholder value —
    spec §9's "do not log tokens or secrets") and truncates long values
    so a span never carries a full payload/prompt/response (spec §21)."""

    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None or is_sensitive_key(key):
            continue
        if isinstance(value, str) and len(value) > _MAX_VALUE_LENGTH:
            value = value[:_MAX_VALUE_LENGTH] + "...(truncated)"
        if isinstance(value, str | bool | int | float):
            safe[key] = value
        else:
            # Never attach an arbitrary object/dict/list as a span
            # attribute — only OTel-primitive types are valid anyway,
            # and this keeps evidence payloads out of spans by
            # construction rather than by remembering to redact them.
            safe[key] = str(type(value).__name__)
    return safe


__all__ = ["is_sensitive_key", "safe_attributes"]
