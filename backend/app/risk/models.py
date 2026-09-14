"""Pure data shapes for the deterministic Risk Engine (Phase 11). No
SQLAlchemy, no Pydantic, no OpenAI/LLM import — same dependency-free
choice as `app/compatibility/models.py`, `app/differential/models.py`,
`app/replay/models.py`.

`RiskContext` is the ONLY input the engine ever sees, and it is built
exclusively from already-computed deterministic evidence (a
`CompatibilityScan`, a `DifferentialReportRecord`, an optional
`BlastRadiusResult`) — never from an OpenAI response. There is no field
here an LLM could populate; `app/services/risk_service.py` is the only
place a `RiskContext` is constructed, and it reads only ORM records and
the blast-radius service.
"""

import enum
import uuid
from dataclasses import dataclass, field


class RiskDecision(enum.StrEnum):
    """The only three outcomes the engine ever produces (spec §7)."""

    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class RiskCategory(enum.StrEnum):
    """Groups rules for the double-counting/per-category-cap policy
    (spec §17) — evidence from one underlying signal (e.g. many
    compatibility changes) contributes to the score once, capped, not
    once per rule that happens to fire on it."""

    COMPATIBILITY = "compatibility"
    REPLAY = "replay"
    DIFFERENTIAL = "differential"
    BLAST_RADIUS = "blast_radius"
    LATENCY = "latency"


@dataclass(frozen=True, slots=True)
class RiskContext:
    """Typed, deterministic-only evidence the engine evaluates rules
    against. Every field defaults to "no signal" (`False`/`0`/`None`),
    so a `RiskContext()` with nothing set is a legitimate "no evidence
    available" input (spec §36) — not an error.

    Fields are pre-aggregated by `RiskService` from ORM records (spec
    §11: the engine itself never queries a database or a graph — it is
    handed plain values).
    """

    # --- from a CompatibilityScan (Phase 5), when one is available ---
    compatibility_status: str | None = None
    """One of CompatibilityStatus's values ("compatible"/"warning"/
    "breaking"), or None when no compatibility scan was supplied."""
    compatibility_breaking_count: int = 0
    compatibility_critical_count: int = 0
    """Count of ScanChange rows at Severity.CRITICAL — reserved for
    changes "certain to break every existing caller" (Phase 5 spec)."""

    # --- from a DifferentialReportRecord (Phase 10), when one is
    # available ---
    differential_available: bool = False
    new_failures: int = 0
    resolved_failures: int = 0
    changed_outputs: int = 0
    schema_changes: int = 0
    removed_steps: int = 0
    has_removed_required_step: bool = False
    """True when a STEP_REMOVED difference exists for a baseline step
    that itself completed successfully — i.e. a step the baseline
    actually needed and executed has disappeared from the candidate,
    not merely an already-dead/skipped step."""
    tool_invocation_changed: bool = False
    """True when any step difference carries TOOL_CHANGED or
    PROVIDER_INVOCATION_CHANGED (spec's TOOL_INVOCATION_CHANGED rule)."""
    error_introduced: bool = False
    """True when any step difference carries ERROR_INTRODUCED."""
    max_latency_percent_delta: float | None = None
    """The largest positive (candidate slower than baseline)
    `latency_percent_delta` observed across step differences, or None
    when no step carries a measured latency comparison."""

    # --- from BlastRadiusService (Phase 4), when the graph is
    # reachable and the compatibility scan's component resolved ---
    blast_radius_total_affected: int | None = None
    """None means "not computed" (graph unavailable, component not yet
    synced) — deliberately distinct from 0 ("computed, nothing
    affected"). A rule keyed on this field must treat None as "no
    signal", never coerce it to 0."""

    # --- provenance, for traceable reasons (spec §20) ---
    compatibility_scan_id: uuid.UUID | None = None
    differential_report_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class TriggeredRule:
    """One rule that fired against a `RiskContext` (spec §20: every
    reason must be traceable back to a named rule and the evidence that
    triggered it)."""

    rule_id: str
    category: RiskCategory
    description: str
    score_delta: int
    """The rule's raw, uncapped contribution — `RiskEngine` applies the
    per-category cap and the overall 100 cap afterward; this field
    always shows the rule's own, un-clamped delta for auditability."""
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    """Stable string pointers into the evidence that triggered this
    rule (e.g. "compatibility_scan:<id>", "differential_report:<id>",
    "differential.summary.new_failures"), never a raw value that might
    carry a secret — reuses `app.trajectory.redaction` if a rule's
    description ever needs to echo an evidence value (spec §29)."""
    hard_block: bool = False
    """True for a hard-block rule (spec §16) — a hard-block rule's
    `score_delta` is always 0: it forces the decision independently of
    the numeric score, it does not additionally inflate it."""


@dataclass(frozen=True, slots=True)
class CategoryContribution:
    """How much one category contributed to the final score, before and
    after its cap — kept for explainability (spec §17/§20)."""

    category: RiskCategory
    raw_total: int
    capped_total: int
    cap: int


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """The complete, deterministic output of evaluating a `RiskContext`
    (spec §5-§9). Pure computation — no database identifiers; that's
    `RiskService`'s job to attach when it persists a
    `RiskAssessmentRecord`."""

    risk_engine_version: str
    decision: RiskDecision
    score: int
    """0-100, already capped. Present even when `hard_block` is true —
    a hard-blocked assessment still reports the score the rules alone
    would have produced, so a human reviewing it can see how close (or
    not) the deterministic signals were on their own."""
    hard_block: bool
    triggered_rules: tuple[TriggeredRule, ...]
    category_contributions: tuple[CategoryContribution, ...]

    @property
    def reasons(self) -> tuple[TriggeredRule, ...]:
        """Alias kept for API/consumer readability — a "reason" is just
        a triggered rule."""
        return self.triggered_rules
