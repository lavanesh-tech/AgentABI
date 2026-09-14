"""The versioned, named rule set (spec §10-§16). Each rule is a small,
pure function `RiskContext -> TriggeredRule | None` — deterministic,
side-effect-free, and independently unit-testable. Adding, removing, or
re-weighting a rule is a `RISK_ENGINE_VERSION` bump
(`app/risk/engine.py`), never an in-place edit whose meaning silently
changes for already-persisted assessments.

Score-rule deltas and hard-block predicates below are this build's
chosen, documented ruleset (ADR — see docs/DECISIONS.md "Phase 11:
deterministic risk scoring"); the spec deliberately leaves the exact
numbers to the implementer ("choose thresholds based on simple
versioned rules; document them").
"""

from collections.abc import Callable

from app.risk.models import RiskCategory, RiskContext, TriggeredRule

RiskRule = Callable[[RiskContext], TriggeredRule | None]

# Latency is only "significant" above this percent regression — chosen
# to filter routine jitter (spec's own example threshold class).
_LATENCY_SIGNIFICANT_PERCENT = 50.0
# Blast radius scoring bands — deliberately coarse (spec §14: "a simple
# deterministic banding is sufficient").
_BLAST_RADIUS_HIGH = 10
_BLAST_RADIUS_MODERATE = 3


def _compat_breaking_change(ctx: RiskContext) -> TriggeredRule | None:
    if ctx.compatibility_status != "breaking" and ctx.compatibility_breaking_count <= 0:
        return None
    return TriggeredRule(
        rule_id="COMPAT_BREAKING_CHANGE",
        category=RiskCategory.COMPATIBILITY,
        description=(
            f"Compatibility scan reported {ctx.compatibility_breaking_count} breaking change(s)"
        ),
        score_delta=30,
        evidence_refs=(
            (f"compatibility_scan:{ctx.compatibility_scan_id}",)
            if ctx.compatibility_scan_id
            else ()
        )
        + ("compatibility.breaking_count",),
    )


def _new_replay_failure(ctx: RiskContext) -> TriggeredRule | None:
    if ctx.new_failures <= 0:
        return None
    return TriggeredRule(
        rule_id="NEW_REPLAY_FAILURE",
        category=RiskCategory.REPLAY,
        description=(
            f"{ctx.new_failures} replay step(s) that passed on the baseline "
            "now fail on the candidate"
        ),
        score_delta=min(15 * ctx.new_failures, 45),
        evidence_refs=(
            (f"differential_report:{ctx.differential_report_id}",)
            if ctx.differential_report_id
            else ()
        )
        + ("differential.summary.new_failures",),
    )


def _removed_required_step(ctx: RiskContext) -> TriggeredRule | None:
    if not ctx.has_removed_required_step:
        return None
    return TriggeredRule(
        rule_id="REMOVED_REQUIRED_STEP",
        category=RiskCategory.DIFFERENTIAL,
        description=(
            "A step that completed successfully on the baseline no longer "
            "appears in the candidate's execution"
        ),
        score_delta=20,
        evidence_refs=(
            (f"differential_report:{ctx.differential_report_id}",)
            if ctx.differential_report_id
            else ()
        )
        + ("differential.step_differences[STEP_REMOVED]",),
    )


def _high_blast_radius(ctx: RiskContext) -> TriggeredRule | None:
    affected = ctx.blast_radius_total_affected
    if affected is None or affected < _BLAST_RADIUS_MODERATE:
        return None
    delta = 20 if affected >= _BLAST_RADIUS_HIGH else 10
    return TriggeredRule(
        rule_id="HIGH_BLAST_RADIUS",
        category=RiskCategory.BLAST_RADIUS,
        description=f"{affected} downstream component(s) depend on the changed component",
        score_delta=delta,
        evidence_refs=("blast_radius.total_affected",),
    )


def _output_schema_break(ctx: RiskContext) -> TriggeredRule | None:
    if ctx.schema_changes <= 0:
        return None
    return TriggeredRule(
        rule_id="OUTPUT_SCHEMA_BREAK",
        category=RiskCategory.DIFFERENTIAL,
        description=f"{ctx.schema_changes} step output(s) changed shape between runs",
        score_delta=20,
        evidence_refs=(
            (f"differential_report:{ctx.differential_report_id}",)
            if ctx.differential_report_id
            else ()
        )
        + ("differential.summary.schema_changes",),
    )


def _tool_invocation_changed(ctx: RiskContext) -> TriggeredRule | None:
    if not ctx.tool_invocation_changed:
        return None
    return TriggeredRule(
        rule_id="TOOL_INVOCATION_CHANGED",
        category=RiskCategory.DIFFERENTIAL,
        description="Which tool/provider a step invokes changed between baseline and candidate",
        score_delta=10,
        evidence_refs=(
            (f"differential_report:{ctx.differential_report_id}",)
            if ctx.differential_report_id
            else ()
        )
        + ("differential.step_differences[TOOL_CHANGED|PROVIDER_INVOCATION_CHANGED]",),
    )


def _error_introduced(ctx: RiskContext) -> TriggeredRule | None:
    if not ctx.error_introduced:
        return None
    return TriggeredRule(
        rule_id="ERROR_INTRODUCED",
        category=RiskCategory.DIFFERENTIAL,
        description="A step that had no error on the baseline now errors on the candidate",
        score_delta=15,
        evidence_refs=(
            (f"differential_report:{ctx.differential_report_id}",)
            if ctx.differential_report_id
            else ()
        )
        + ("differential.step_differences[ERROR_INTRODUCED]",),
    )


def _significant_latency_increase(ctx: RiskContext) -> TriggeredRule | None:
    delta = ctx.max_latency_percent_delta
    if delta is None or delta < _LATENCY_SIGNIFICANT_PERCENT:
        return None
    return TriggeredRule(
        rule_id="SIGNIFICANT_LATENCY_INCREASE",
        category=RiskCategory.LATENCY,
        description=f"Candidate latency regressed by {delta:.0f}% on at least one step",
        score_delta=10,
        evidence_refs=("differential.step_differences[LATENCY_CHANGED]",),
    )


# Discoverable, ordered ruleset — evaluation order is the order reasons
# appear in a `RiskAssessment` (deterministic output ordering, spec
# §21). Each `rule_id` below is a permanent identifier; renaming one is
# a `RISK_ENGINE_VERSION` bump like any other rule-set change.
SCORE_RULES: tuple[RiskRule, ...] = (
    _compat_breaking_change,
    _new_replay_failure,
    _removed_required_step,
    _high_blast_radius,
    _output_schema_break,
    _tool_invocation_changed,
    _error_introduced,
    _significant_latency_increase,
)

# Per-category cap (spec §17's double-counting policy): several rules in
# the same category can fire on related evidence (e.g. OUTPUT_SCHEMA_
# BREAK and TOOL_INVOCATION_CHANGED both stem from the same differential
# report); their combined contribution to the score is capped per
# category rather than left to sum unbounded.
CATEGORY_CAPS: dict[RiskCategory, int] = {
    RiskCategory.COMPATIBILITY: 40,
    RiskCategory.REPLAY: 45,
    RiskCategory.DIFFERENTIAL: 50,
    RiskCategory.BLAST_RADIUS: 20,
    RiskCategory.LATENCY: 15,
}

MAX_SCORE = 100


def _hard_block_critical_compat_break(ctx: RiskContext) -> TriggeredRule | None:
    if ctx.compatibility_critical_count <= 0:
        return None
    return TriggeredRule(
        rule_id="HARD_BLOCK_CRITICAL_COMPAT_BREAK",
        category=RiskCategory.COMPATIBILITY,
        description=(
            f"{ctx.compatibility_critical_count} CRITICAL-severity compatibility "
            "change(s) certain to break every existing caller"
        ),
        score_delta=0,
        evidence_refs=(
            (f"compatibility_scan:{ctx.compatibility_scan_id}",)
            if ctx.compatibility_scan_id
            else ()
        )
        + ("compatibility.critical_count",),
        hard_block=True,
    )


def _hard_block_replay_failure_on_passing_baseline(ctx: RiskContext) -> TriggeredRule | None:
    if ctx.new_failures <= 0:
        return None
    return TriggeredRule(
        rule_id="HARD_BLOCK_NEW_REPLAY_FAILURE",
        category=RiskCategory.REPLAY,
        description=(
            f"{ctx.new_failures} step(s) that passed on the baseline replay fail "
            "on the candidate — a regression the score alone must not be able to "
            "average away"
        ),
        score_delta=0,
        evidence_refs=(
            (f"differential_report:{ctx.differential_report_id}",)
            if ctx.differential_report_id
            else ()
        )
        + ("differential.summary.new_failures",),
        hard_block=True,
    )


# Hard-block rules are score-independent (spec §16): if any fires, the
# decision is BLOCK regardless of what `SCORE_RULES` alone would have
# produced. They intentionally overlap in predicate with a `SCORE_RULES`
# entry sometimes (e.g. NEW_REPLAY_FAILURE / HARD_BLOCK_NEW_REPLAY_
# FAILURE both key off `new_failures`) — that duplication is deliberate,
# not a bug: the score rule keeps the numeric score meaningful even when
# a human overrides/ignores the hard block, while the hard-block rule
# guarantees the decision itself can never be "averaged away" by other,
# unrelated evidence scoring low.
HARD_BLOCK_RULES: tuple[RiskRule, ...] = (
    _hard_block_critical_compat_break,
    _hard_block_replay_failure_on_passing_baseline,
)
