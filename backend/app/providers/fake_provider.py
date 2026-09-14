"""Deterministic fake `LLMProvider` for tests (spec §19). No network, no
API key, no OpenAI SDK import — safe to use in every unit test without
risk of spending real API credits.
"""

from dataclasses import dataclass

from app.domain.exceptions import LLMExplanationFailed, LLMProviderTimeout
from app.llm.models import EvidenceReference, ExplanationRequest, ExplanationResponse


@dataclass
class FakeLLMProvider:
    """Configurable behavior for tests:
    - default: returns a canned, deterministic `ExplanationResponse`
      that cites every `reference_id` in the request's evidence.
    - `mode="timeout"`: raises `LLMProviderTimeout`.
    - `mode="error"`: raises `LLMExplanationFailed`.
    - `mode="invalid_reference"`: returns a response citing a
      `reference_id` NOT present in the request, to exercise
      `ExplanationService`'s reference validation.
    """

    mode: str = "success"
    provider_name: str = "fake"
    model: str = "fake-model"
    calls: list[ExplanationRequest] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    async def explain(self, request: ExplanationRequest) -> ExplanationResponse:
        self.calls.append(request)

        if self.mode == "timeout":
            raise LLMProviderTimeout(self.provider_name, timeout_seconds=30.0)
        if self.mode == "error":
            raise LLMExplanationFailed(self.provider_name, "simulated provider failure")

        if self.mode == "invalid_reference":
            references = (EvidenceReference(reference_id="not-a-real-id", note="fabricated"),)
        else:
            references = tuple(
                EvidenceReference(reference_id=item.reference_id) for item in request.evidence
            )

        limitations = ("Evidence was truncated before this explanation was generated.",)
        return ExplanationResponse(
            summary=f"Fake explanation of {request.subject}.",
            key_findings=(f"{len(request.evidence)} evidence item(s) supplied.",),
            likely_impact=("Impact described only from supplied evidence.",),
            remediation_steps=("Review the cited evidence directly.",),
            evidence_references=references,
            limitations=limitations if request.truncated else (),
            provider=self.provider_name,
            model=self.model,
        )
