"""Deterministic input bounding for the LLM explanation layer (spec
§13). The LLM never decides what evidence to drop — this module does,
by fixed, documented rules, before an `ExplanationRequest` is ever
built. Pure functions, no I/O, fully unit-testable without a provider.
"""

from dataclasses import dataclass

from app.llm.models import EvidenceItem

MAX_EVIDENCE_ITEMS = 25
MAX_DETAIL_CHARS = 500
MAX_SUMMARY_CHARS = 200


@dataclass(frozen=True, slots=True)
class BoundedEvidence:
    items: tuple[EvidenceItem, ...]
    truncated: bool
    original_count: int


def bound_evidence(
    items: list[EvidenceItem] | tuple[EvidenceItem, ...],
    *,
    max_items: int = MAX_EVIDENCE_ITEMS,
) -> BoundedEvidence:
    """Truncate the evidence list to `max_items`, and clip each item's
    `summary`/`detail` text length. Ordering is preserved (callers are
    expected to have already sorted by importance, e.g. severity) —
    this function only enforces the ceiling, it never reorders."""

    original_count = len(items)
    kept = items[:max_items]
    clipped = tuple(_clip(item) for item in kept)
    return BoundedEvidence(
        items=clipped,
        truncated=original_count > len(clipped),
        original_count=original_count,
    )


def _clip(item: EvidenceItem) -> EvidenceItem:
    summary = item.summary
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[: MAX_SUMMARY_CHARS - 1] + "…"
    detail = item.detail
    if len(detail) > MAX_DETAIL_CHARS:
        detail = detail[: MAX_DETAIL_CHARS - 1] + "…"
    if summary == item.summary and detail == item.detail:
        return item
    return EvidenceItem(
        kind=item.kind, reference_id=item.reference_id, summary=summary, detail=detail
    )
