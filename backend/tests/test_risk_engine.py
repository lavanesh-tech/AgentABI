"""Pure tests for `app/risk/engine.py` — thresholds, reproducibility,
hard-block interaction, score cap, ordering, no-evidence (Phase 11 spec
§32-§36). No SQLAlchemy/FastAPI import, runs for real via `pytest
--noconftest`.
"""

from app.risk.engine import RISK_ENGINE_VERSION, _decide, evaluate
from app.risk.models import RiskContext, RiskDecision


def test_no_evidence_is_pass_with_zero_score():
    result = evaluate(RiskContext())
    assert result.score == 0
    assert result.decision is RiskDecision.PASS
    assert result.hard_block is False
    assert result.triggered_rules == ()


def test_decision_threshold_exact_boundaries():
    # PASS < 30, WARN 30-69, BLOCK >= 70 (spec §33) — exercised directly
    # against `_decide` (score, hard_block=False) so the boundary logic
    # is verified independent of which integer deltas the current
    # ruleset happens to produce.
    assert _decide(29, hard_block=False) is RiskDecision.PASS
    assert _decide(30, hard_block=False) is RiskDecision.WARN
    assert _decide(69, hard_block=False) is RiskDecision.WARN
    assert _decide(70, hard_block=False) is RiskDecision.BLOCK
    assert _decide(100, hard_block=False) is RiskDecision.BLOCK
    # hard_block=True forces BLOCK regardless of score, including 0.
    assert _decide(0, hard_block=True) is RiskDecision.BLOCK


def test_decision_threshold_boundaries_via_real_rule_combinations():
    # Sanity-check the same bands through `evaluate()` with realistic
    # rule combinations (deltas here are all multiples of 5, so these
    # land near, not necessarily exactly on, 29/30/69/70).
    schema_only = evaluate(RiskContext(schema_changes=1))
    assert schema_only.score == 20
    assert schema_only.decision is RiskDecision.PASS

    schema_and_tool = evaluate(RiskContext(schema_changes=1, tool_invocation_changed=True))
    assert schema_and_tool.score == 30
    assert schema_and_tool.decision is RiskDecision.WARN

    schema_tool_error = evaluate(
        RiskContext(schema_changes=1, tool_invocation_changed=True, error_introduced=True)
    )
    # DIFFERENTIAL: 20 + 10 + 15 = 45, under that category's 50 cap.
    assert schema_tool_error.score == 45
    assert schema_tool_error.decision is RiskDecision.WARN

    compat_and_replay = evaluate(
        RiskContext(compatibility_status="breaking", compatibility_breaking_count=1, new_failures=3)
    )
    # COMPATIBILITY 30 + REPLAY min(15*3, 45)=45 -> 75 (also hard-
    # blocked via new_failures, independently forcing BLOCK).
    assert compat_and_replay.score == 75
    assert compat_and_replay.decision is RiskDecision.BLOCK


def test_score_never_exceeds_100():
    ctx = RiskContext(
        compatibility_status="breaking",
        compatibility_breaking_count=10,
        compatibility_critical_count=5,
        new_failures=20,
        has_removed_required_step=True,
        blast_radius_total_affected=999,
        schema_changes=50,
        tool_invocation_changed=True,
        error_introduced=True,
        max_latency_percent_delta=500.0,
    )
    result = evaluate(ctx)
    assert result.score == 100
    assert result.decision is RiskDecision.BLOCK


def test_reproducibility_same_context_same_result():
    ctx = RiskContext(schema_changes=1, tool_invocation_changed=True, new_failures=1)
    first = evaluate(ctx)
    second = evaluate(ctx)
    assert first.score == second.score
    assert first.decision == second.decision
    assert first.hard_block == second.hard_block
    assert [r.rule_id for r in first.triggered_rules] == [r.rule_id for r in second.triggered_rules]
    assert first.risk_engine_version == second.risk_engine_version == RISK_ENGINE_VERSION


def test_hard_block_forces_block_even_at_low_score():
    # compatibility_critical_count alone contributes 0 score (hard-block
    # rules never carry a score_delta) — score stays low, decision is
    # still forced to BLOCK.
    result = evaluate(RiskContext(compatibility_critical_count=1))
    assert result.score == 0
    assert result.hard_block is True
    assert result.decision is RiskDecision.BLOCK
    hard_block_reasons = [r for r in result.triggered_rules if r.hard_block]
    assert len(hard_block_reasons) == 1
    assert hard_block_reasons[0].rule_id == "HARD_BLOCK_CRITICAL_COMPAT_BREAK"


def test_double_counting_capped_per_category():
    # Three DIFFERENTIAL-category rules (20 + 10 + 15 = 45) stay under
    # that category's 50 cap here, but combined with REMOVED_REQUIRED_
    # STEP (+20 more, also DIFFERENTIAL) the raw total (65) exceeds the
    # cap and is clamped to 50 (spec §16's double-counting policy).
    ctx = RiskContext(
        schema_changes=1,
        tool_invocation_changed=True,
        error_introduced=True,
        has_removed_required_step=True,
    )
    result = evaluate(ctx)
    differential_contribution = next(
        c for c in result.category_contributions if c.category.value == "differential"
    )
    assert differential_contribution.raw_total == 65
    assert differential_contribution.capped_total == 50
    assert result.score == 50


def test_deterministic_rule_ordering_matches_declaration_order():
    ctx = RiskContext(
        error_introduced=True,
        schema_changes=1,
        tool_invocation_changed=True,
    )
    result = evaluate(ctx)
    ids = [r.rule_id for r in result.triggered_rules]
    # Declared SCORE_RULES order: schema break precedes tool-invocation
    # precedes error-introduced, regardless of which fields were set
    # first on the context.
    assert ids == ["OUTPUT_SCHEMA_BREAK", "TOOL_INVOCATION_CHANGED", "ERROR_INTRODUCED"]


def test_resolved_failures_do_not_increase_score():
    result = evaluate(RiskContext(resolved_failures=10))
    assert result.score == 0
    assert result.decision is RiskDecision.PASS
