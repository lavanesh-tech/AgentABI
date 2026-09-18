"""OpenAIProvider tests against a mocked `openai` SDK boundary (spec
§27). No real network call, no API credits spent. Requires the `openai`
package to be importable (it's a declared dependency — see
pyproject.toml) but never actually reaches the network: `openai.
AsyncOpenAI` itself is monkeypatched out.

Not runnable in this sandbox (the `openai` package, like fastapi/
sqlalchemy, isn't installable here — see docs/SECURITY_VERIFICATION.md-
style sandbox notes in docs/DECISIONS.md); written and `py_compile`-clean.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.domain.exceptions import (
    LLMExplanationFailed,
    LLMInvalidResponse,
    LLMProviderNotConfigured,
    LLMProviderTimeout,
)
from app.llm.models import EvidenceItem, ExplanationRequest
from app.providers.openai_provider import OpenAIProvider

pytest.importorskip("openai")


def _request() -> ExplanationRequest:
    item = EvidenceItem(
        kind="compatibility_change", reference_id="change:0:FIELD_ADDED", summary="s", detail="d"
    )
    return ExplanationRequest(
        subject="scan",
        baseline_label="v1",
        candidate_label="v2",
        evidence=(item,),
        allowed_reference_ids=frozenset({item.reference_id}),
    )


def _valid_payload(reference_id: str) -> str:
    return json.dumps(
        {
            "summary": "A field was added.",
            "key_findings": ["field added"],
            "likely_impact": ["callers unaffected"],
            "remediation_steps": ["no action needed"],
            "evidence_references": [{"reference_id": reference_id, "note": ""}],
            "limitations": [],
        }
    )


@pytest.mark.asyncio
async def test_missing_api_key_raises_not_configured():
    provider = OpenAIProvider(api_key=None, model="gpt-4o-mini", timeout_seconds=30, max_retries=2)
    with pytest.raises(LLMProviderNotConfigured):
        await provider.explain(_request())


@pytest.mark.asyncio
async def test_success_uses_configured_model_and_structured_schema(monkeypatch):
    import openai

    request = _request()
    fake_response = SimpleNamespace(
        output_text=_valid_payload("change:0:FIELD_ADDED"),
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )
    mock_create = AsyncMock(return_value=fake_response)
    mock_client = SimpleNamespace(responses=SimpleNamespace(create=mock_create))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: mock_client)

    provider = OpenAIProvider(
        api_key="sk-test", model="gpt-4o-mini", timeout_seconds=30, max_retries=2
    )
    result = await provider.explain(request)

    assert result.summary == "A field was added."
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    assert call_kwargs["text"]["format"]["type"] == "json_schema"
    assert call_kwargs["text"]["format"]["strict"] is True


@pytest.mark.asyncio
async def test_timeout_is_mapped(monkeypatch):
    import openai

    mock_create = AsyncMock(side_effect=openai.APITimeoutError(request=None))
    mock_client = SimpleNamespace(responses=SimpleNamespace(create=mock_create))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: mock_client)

    provider = OpenAIProvider(
        api_key="sk-test", model="gpt-4o-mini", timeout_seconds=30, max_retries=2
    )
    with pytest.raises(LLMProviderTimeout):
        await provider.explain(_request())


@pytest.mark.asyncio
async def test_malformed_response_is_invalid_response(monkeypatch):
    import openai

    fake_response = SimpleNamespace(output_text="not json")
    mock_create = AsyncMock(return_value=fake_response)
    mock_client = SimpleNamespace(responses=SimpleNamespace(create=mock_create))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: mock_client)

    provider = OpenAIProvider(
        api_key="sk-test", model="gpt-4o-mini", timeout_seconds=30, max_retries=2
    )
    with pytest.raises(LLMInvalidResponse):
        await provider.explain(_request())


@pytest.mark.asyncio
async def test_empty_response_is_invalid_response(monkeypatch):
    import openai

    fake_response = SimpleNamespace(output_text="")
    mock_create = AsyncMock(return_value=fake_response)
    mock_client = SimpleNamespace(responses=SimpleNamespace(create=mock_create))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: mock_client)

    provider = OpenAIProvider(
        api_key="sk-test", model="gpt-4o-mini", timeout_seconds=30, max_retries=2
    )
    with pytest.raises(LLMInvalidResponse):
        await provider.explain(_request())


@pytest.mark.asyncio
async def test_fabricated_evidence_reference_is_rejected(monkeypatch):
    import openai

    fake_response = SimpleNamespace(output_text=_valid_payload("not-a-real-reference"))
    mock_create = AsyncMock(return_value=fake_response)
    mock_client = SimpleNamespace(responses=SimpleNamespace(create=mock_create))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: mock_client)

    provider = OpenAIProvider(
        api_key="sk-test", model="gpt-4o-mini", timeout_seconds=30, max_retries=2
    )
    with pytest.raises(LLMInvalidResponse):
        await provider.explain(_request())


@pytest.mark.asyncio
async def test_authentication_error_is_sanitized(monkeypatch):
    import openai

    mock_create = AsyncMock(
        side_effect=openai.AuthenticationError(
            message="bad key",
            response=httpx.Response(
                401,
                headers={},
                request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
            ),
            body=None,
        )
    )
    mock_client = SimpleNamespace(responses=SimpleNamespace(create=mock_create))
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: mock_client)

    provider = OpenAIProvider(
        api_key="sk-test", model="gpt-4o-mini", timeout_seconds=30, max_retries=2
    )
    with pytest.raises(LLMExplanationFailed) as exc_info:
        await provider.explain(_request())
    assert "sk-test" not in str(exc_info.value)
