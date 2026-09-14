"""ExplanationService tests using FakeLLMProvider — no network, no API
key, no OpenAI SDK import (spec §19/§26). Covers success, timeout,
provider error, invalid-reference rejection, and evidence-bounding
wiring end-to-end through the service."""

from dataclasses import dataclass
from typing import Any

import pytest

from app.domain.exceptions import LLMExplanationFailed, LLMInvalidResponse, LLMProviderTimeout
from app.providers.fake_provider import FakeLLMProvider
from app.services.explanation_service import ExplanationService


@dataclass
class _FakeChange:
    change_type: Any
    path: str
    classification: Any
    severity: Any
    message: str
    old_value: Any = None
    new_value: Any = None


def _changes(n: int) -> list[_FakeChange]:
    return [
        _FakeChange(
            change_type=f"FIELD_ADDED_{i}",
            path=f"$.field{i}",
            classification="breaking",
            severity="high",
            message=f"field{i} added",
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_success_returns_explanation_with_references():
    provider = FakeLLMProvider(mode="success")
    service = ExplanationService(provider)

    result = await service.explain_compatibility_changes(
        subject="scan X",
        baseline_label="v1",
        candidate_label="v2",
        changes=_changes(3),
    )

    assert result.summary
    assert len(result.evidence_references) == 3
    assert len(provider.calls) == 1
    assert provider.calls[0].evidence[0].kind == "compatibility_change"


@pytest.mark.asyncio
async def test_timeout_propagates_as_domain_error():
    service = ExplanationService(FakeLLMProvider(mode="timeout"))
    with pytest.raises(LLMProviderTimeout):
        await service.explain_compatibility_changes(
            subject="s", baseline_label="a", candidate_label="b", changes=_changes(1)
        )


@pytest.mark.asyncio
async def test_provider_error_propagates_as_domain_error():
    service = ExplanationService(FakeLLMProvider(mode="error"))
    with pytest.raises(LLMExplanationFailed):
        await service.explain_compatibility_changes(
            subject="s", baseline_label="a", candidate_label="b", changes=_changes(1)
        )


@pytest.mark.asyncio
async def test_invalid_evidence_reference_is_rejected():
    service = ExplanationService(FakeLLMProvider(mode="invalid_reference"))
    with pytest.raises(LLMInvalidResponse):
        await service.explain_compatibility_changes(
            subject="s", baseline_label="a", candidate_label="b", changes=_changes(1)
        )


@pytest.mark.asyncio
async def test_evidence_over_the_bound_is_truncated_and_flagged():
    provider = FakeLLMProvider(mode="success")
    service = ExplanationService(provider)

    await service.explain_compatibility_changes(
        subject="s", baseline_label="a", candidate_label="b", changes=_changes(40)
    )

    sent_request = provider.calls[0]
    assert sent_request.truncated is True
    assert len(sent_request.evidence) == 25


@pytest.mark.asyncio
async def test_no_changes_produces_empty_evidence_request():
    provider = FakeLLMProvider(mode="success")
    service = ExplanationService(provider)

    result = await service.explain_compatibility_changes(
        subject="s", baseline_label="a", candidate_label="b", changes=[]
    )

    assert provider.calls[0].evidence == ()
    assert result.evidence_references == ()
