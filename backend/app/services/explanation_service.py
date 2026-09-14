"""ExplanationService — the single place deterministic AgentABI evidence
is turned into an `ExplanationRequest` and handed to an `LLMProvider`
(spec §18). Routes never call a provider directly; this service bounds
evidence, builds the request, invokes the provider, and validates the
response's evidence references before returning.

Testable entirely with `app.providers.fake_provider.FakeLLMProvider` —
no network, no API key, no OpenAI SDK import anywhere in this module.
"""

import uuid
from typing import Any, Protocol

from app.domain.exceptions import LLMInvalidResponse
from app.llm.bounding import bound_evidence
from app.llm.models import EvidenceItem, ExplanationRequest, ExplanationResponse
from app.llm.provider import LLMProvider


class ChangeLike(Protocol):
    """Structural shape shared by `app.compatibility.models.Change`
    (pure dataclass, `change_type` is a `ChangeType` enum) and
    `app.models.scan_change.ScanChange` (persisted ORM row,
    `change_type` is a plain `str`) — this service accepts either
    without importing SQLAlchemy or coupling to one specific type."""

    change_type: Any
    path: str
    classification: Any
    severity: Any
    message: str
    old_value: Any
    new_value: Any


class ExplanationService:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def explain_compatibility_changes(
        self,
        *,
        subject: str,
        baseline_label: str,
        candidate_label: str,
        changes: list[ChangeLike],
        correlation_id: str | None = None,
    ) -> ExplanationResponse:
        """Builds a bounded `ExplanationRequest` from a compatibility
        scan's deterministic change list (either the pure `Change`
        dataclass or a persisted `ScanChange` row — see `ChangeLike`),
        in worst-first order (the caller is expected to have already
        sorted `changes` — this method does not re-sort), and returns
        the provider's validated `ExplanationResponse`."""

        items = [
            EvidenceItem(
                kind="compatibility_change",
                reference_id=f"change:{index}:{_enum_value(change.change_type)}",
                summary=change.message,
                detail=_change_detail(change),
            )
            for index, change in enumerate(changes)
        ]
        return await self._explain(
            subject=subject,
            baseline_label=baseline_label,
            candidate_label=candidate_label,
            items=items,
            correlation_id=correlation_id,
        )

    async def _explain(
        self,
        *,
        subject: str,
        baseline_label: str,
        candidate_label: str,
        items: list[EvidenceItem],
        correlation_id: str | None,
    ) -> ExplanationResponse:
        bounded = bound_evidence(items)
        allowed_ids = frozenset(item.reference_id for item in bounded.items)

        request = ExplanationRequest(
            subject=subject,
            baseline_label=baseline_label,
            candidate_label=candidate_label,
            evidence=bounded.items,
            allowed_reference_ids=allowed_ids,
            truncated=bounded.truncated,
            correlation_id=correlation_id or str(uuid.uuid4()),
        )

        response = await self._provider.explain(request)
        _validate_response_references(response, allowed_ids)
        return response


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _change_detail(change: ChangeLike) -> str:
    parts = [
        f"classification={_enum_value(change.classification)}",
        f"severity={_enum_value(change.severity)}",
    ]
    if change.old_value is not None:
        parts.append(f"old={change.old_value!r}")
    if change.new_value is not None:
        parts.append(f"new={change.new_value!r}")
    return f"path={change.path}; " + "; ".join(parts)


def _validate_response_references(
    response: ExplanationResponse, allowed_ids: frozenset[str]
) -> None:
    """Defense in depth (spec §12): `OpenAIProvider` already validates
    references against its own request, but the service validates again
    against its own bounded evidence so a future/misbehaving provider
    can never leak a fabricated reference id through this boundary."""

    invalid = [
        r.reference_id for r in response.evidence_references if r.reference_id not in allowed_ids
    ]
    if invalid:
        raise LLMInvalidResponse(
            "unknown", f"response cited unknown evidence reference(s): {invalid}"
        )
