"""`OpenAIProvider` — the only file in this codebase that imports the
OpenAI SDK. Implements `app.llm.provider.LLMProvider`; every OpenAI-
specific type (client, response objects, SDK exceptions) is created,
used, and mapped to domain types entirely inside this module — nothing
OpenAI-shaped ever returns from `explain()` (spec §4).

Uses the Responses API (spec §5) with Structured Outputs (JSON Schema,
`strict: True`) so the model's reply is guaranteed to match
`_ExplanationSchema` exactly, rather than relying on prompt-only JSON
formatting and brittle free-form parsing.
"""

import json
import time
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.domain.exceptions import (
    LLMExplanationFailed,
    LLMInvalidResponse,
    LLMProviderNotConfigured,
    LLMProviderTimeout,
    LLMProviderUnavailable,
)
from app.llm.models import EvidenceReference, ExplanationRequest, ExplanationResponse
from app.llm.prompts import EXPLANATION_SYSTEM_PROMPT
from app.observability import record_openai_explanation, start_span

PROVIDER_NAME = "openai"

logger = structlog.get_logger(__name__)


class _EvidenceReferenceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str
    note: str


class _ExplanationSchema(BaseModel):
    """Internal-only Pydantic model used purely to request/parse OpenAI's
    Structured Output — never imported outside this module, never
    returned from `explain()`. Converted to the provider-agnostic
    `app.llm.models.ExplanationResponse` before returning."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    key_findings: list[str]
    likely_impact: list[str]
    remediation_steps: list[str]
    evidence_references: list[_EvidenceReferenceSchema]
    limitations: list[str]


class OpenAIProvider:
    """Constructed once per request via `app/api/deps/llm.py`'s factory.
    Cheap to construct (the SDK client itself is lightweight); no
    connection is opened until `explain()` is called."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def explain(self, request: ExplanationRequest) -> ExplanationResponse:
        """Phase 15 spec §21 provider-boundary span. Never carries the
        API key, prompt, or response — only provider/model/outcome."""

        settings = get_settings()
        start = time.monotonic()
        outcome = "success"
        with start_span(
            "agentabi.openai.explain",
            kind="client",
            attributes={"agentabi.provider": PROVIDER_NAME, "agentabi.model": self._model},
        ):
            try:
                return await self._explain_impl(request)
            except Exception:
                outcome = "failure"
                raise
            finally:
                record_openai_explanation(
                    settings,
                    outcome=outcome,
                    model=self._model,
                    duration_seconds=time.monotonic() - start,
                )

    async def _explain_impl(self, request: ExplanationRequest) -> ExplanationResponse:
        if not self._api_key:
            raise LLMProviderNotConfigured(PROVIDER_NAME)

        # Imported lazily so the rest of the application (including every
        # deterministic module and every test that never calls this
        # provider) never requires the `openai` package to be installed
        # or importable — see spec §31's architectural invariant.
        import openai

        client = openai.AsyncOpenAI(
            api_key=self._api_key,
            timeout=self._timeout_seconds,
            max_retries=self._max_retries,
        )

        schema = _ExplanationSchema.model_json_schema()
        schema["additionalProperties"] = False
        user_payload = _build_user_payload(request)

        start = time.monotonic()
        try:
            response = await client.responses.create(
                model=self._model,
                instructions=EXPLANATION_SYSTEM_PROMPT,
                input=json.dumps(user_payload),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "agentabi_explanation",
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
        except openai.APITimeoutError as exc:
            _log_call(request, self._model, start, "timeout")
            raise LLMProviderTimeout(PROVIDER_NAME, self._timeout_seconds) from exc
        except openai.APIConnectionError as exc:
            _log_call(request, self._model, start, "error")
            raise LLMProviderUnavailable(PROVIDER_NAME, "connection error") from exc
        except openai.AuthenticationError as exc:
            # Never include exc's raw body/headers — they may echo the key.
            _log_call(request, self._model, start, "error")
            raise LLMExplanationFailed(PROVIDER_NAME, "authentication failed") from exc
        except openai.RateLimitError as exc:
            _log_call(request, self._model, start, "error")
            raise LLMExplanationFailed(PROVIDER_NAME, "provider rate limit exceeded") from exc
        except openai.APIStatusError as exc:
            _log_call(request, self._model, start, "error")
            raise LLMExplanationFailed(PROVIDER_NAME, f"upstream status {exc.status_code}") from exc
        except openai.OpenAIError as exc:
            _log_call(request, self._model, start, "error")
            raise LLMExplanationFailed(PROVIDER_NAME, "unexpected provider error") from exc

        parsed = _parse_response(response)
        _validate_references(parsed, request.allowed_reference_ids)
        usage = getattr(response, "usage", None)
        _log_call(
            request,
            self._model,
            start,
            "success",
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

        return ExplanationResponse(
            summary=parsed.summary,
            key_findings=tuple(parsed.key_findings),
            likely_impact=tuple(parsed.likely_impact),
            remediation_steps=tuple(parsed.remediation_steps),
            evidence_references=tuple(
                EvidenceReference(reference_id=r.reference_id, note=r.note)
                for r in parsed.evidence_references
            ),
            limitations=tuple(parsed.limitations),
            provider=PROVIDER_NAME,
            model=self._model,
        )


def _build_user_payload(request: ExplanationRequest) -> dict[str, Any]:
    return {
        "subject": request.subject,
        "baseline_label": request.baseline_label,
        "candidate_label": request.candidate_label,
        "truncated": request.truncated,
        "evidence": [
            {
                "kind": item.kind,
                "reference_id": item.reference_id,
                "summary": item.summary,
                "detail": item.detail,
            }
            for item in request.evidence
        ],
    }


def _parse_response(response: Any) -> _ExplanationSchema:
    output_text = getattr(response, "output_text", None)
    if not output_text:
        raise LLMInvalidResponse(PROVIDER_NAME, "empty or refused response")
    try:
        data = json.loads(output_text)
        return _ExplanationSchema.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMInvalidResponse(PROVIDER_NAME, "response did not match expected schema") from exc


def _validate_references(parsed: _ExplanationSchema, allowed_ids: frozenset[str]) -> None:
    invalid = [
        r.reference_id for r in parsed.evidence_references if r.reference_id not in allowed_ids
    ]
    if invalid:
        raise LLMInvalidResponse(
            PROVIDER_NAME, f"response cited unknown evidence reference(s): {invalid}"
        )


def _log_call(
    request: ExplanationRequest,
    model: str,
    start: float,
    outcome: str,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    # Safe fields only (spec §16): never the prompt, never the API key,
    # never raw SDK headers/error bodies.
    logger.info(
        "llm_explanation_call",
        provider=PROVIDER_NAME,
        model=model,
        outcome=outcome,
        duration_ms=round((time.monotonic() - start) * 1000, 1),
        evidence_item_count=len(request.evidence),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        correlation_id=request.correlation_id,
    )
