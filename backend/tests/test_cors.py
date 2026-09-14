"""CORS configuration — pure unit tests (Security Phase D spec §10/§23).
`build_cors_kwargs` has no FastAPI import, so this runs for real via
`pytest --noconftest`.
"""

import pytest

from app.core.cors import build_cors_kwargs


def test_configured_origin_is_included_verbatim():
    kwargs = build_cors_kwargs(allow_origins=["http://localhost:3000"], allow_credentials=True)
    assert kwargs["allow_origins"] == ["http://localhost:3000"]
    assert kwargs["allow_credentials"] is True


def test_production_trusted_origin_is_included_verbatim():
    kwargs = build_cors_kwargs(
        allow_origins=["https://app.agentabi.example"], allow_credentials=True
    )
    assert kwargs["allow_origins"] == ["https://app.agentabi.example"]


def test_unconfigured_origin_is_not_present():
    kwargs = build_cors_kwargs(
        allow_origins=["https://app.agentabi.example"], allow_credentials=True
    )
    assert "https://evil.example" not in kwargs["allow_origins"]


def test_wildcard_with_credentials_is_rejected():
    with pytest.raises(ValueError):
        build_cors_kwargs(allow_origins=["*"], allow_credentials=True)


def test_wildcard_without_credentials_is_allowed():
    kwargs = build_cors_kwargs(allow_origins=["*"], allow_credentials=False)
    assert kwargs["allow_origins"] == ["*"]
    assert kwargs["allow_credentials"] is False


def test_methods_and_headers_are_not_wildcarded():
    kwargs = build_cors_kwargs(allow_origins=["http://localhost:3000"], allow_credentials=True)
    assert "*" not in kwargs["allow_methods"]
    assert "*" not in kwargs["allow_headers"]
    assert "Authorization" in kwargs["allow_headers"]
