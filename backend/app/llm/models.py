"""Pure data shapes for the LLM explanation layer (Phase 8). No
SQLAlchemy, no Pydantic, no OpenAI SDK types — mirrors the dependency-
free choice made for `app/compatibility/models.py` (Phase 5) and
`app/replay/models.py` (Phase 7), so the deterministic core (and its
tests) never import anything provider-specific.

`ExplanationRequest` carries only already-computed, already-bounded
evidence — never raw ORM rows, never secrets. `ExplanationResponse`
deliberately has NO risk/decision field (no `risk_score`, `pass`,
`compatibility_status`, etc.) — see `app/services/explanation_service.py`
and docs/DECISIONS.md for why that boundary is enforced structurally,
not just by prompt instruction.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One piece of already-computed deterministic evidence handed to the
    LLM to explain. `kind` groups evidence for prompt construction
    (compatibility_change / blast_radius / replay_mismatch / metric);
    `reference_id` is the only identifier the model may cite back in
    `EvidenceReference.reference_id` — never a DB primary key exposed
    directly unless it was already safe to include here."""

    kind: Literal["compatibility_change", "blast_radius", "replay_mismatch", "metric"]
    reference_id: str
    summary: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ExplanationRequest:
    """Bounded, typed input to an `LLMProvider`. Built exclusively by
    `ExplanationService` — never constructed directly from API/service
    layers with unbounded evidence (see `app/llm/bounding.py`)."""

    subject: str
    """Short human description of what's being explained, e.g.
    "compatibility scan of component X from v1 to v2"."""

    baseline_label: str
    candidate_label: str
    evidence: tuple[EvidenceItem, ...]
    allowed_reference_ids: frozenset[str]
    """The exact set of `reference_id`s the model is allowed to cite in
    its output — computed from `evidence`, used to reject invented
    references (spec §12)."""

    truncated: bool = False
    """True if `ExplanationService` had to drop evidence to stay within
    bounds — surfaced to the model and to `ExplanationResponse.
    limitations` (spec §13)."""

    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    reference_id: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class ExplanationResponse:
    """The LLM's structured output. Deliberately contains no
    `risk_score`/`pass`/`warn`/`block`/`compatibility_status`/
    `final_decision` field — see spec §10 and docs/DECISIONS.md. Any
    severity language in `summary`/`key_findings`/`likely_impact` is
    explanatory prose only, never a field this codebase reads as a
    decision."""

    summary: str
    key_findings: tuple[str, ...]
    likely_impact: tuple[str, ...]
    remediation_steps: tuple[str, ...]
    evidence_references: tuple[EvidenceReference, ...]
    limitations: tuple[str, ...] = field(default_factory=tuple)

    provider: str = ""
    model: str = ""


@dataclass(frozen=True, slots=True)
class ExplanationUsage:
    """Safe-to-log provider call metadata (spec §16/§24/§30) — never the
    prompt itself, never secrets."""

    provider: str
    model: str
    duration_ms: float
    outcome: Literal["success", "error", "timeout"]
    input_tokens: int | None = None
    output_tokens: int | None = None
    evidence_item_count: int = 0
