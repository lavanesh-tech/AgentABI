"""Pure unit tests for each named rule in `app/risk/rules.py` (Phase 11
spec §32). No SQLAlchemy/FastAPI import anywhere in `app/risk/`, so this
runs for real via `pytest --noconftest`.
"""

from app.risk.models import RiskCategory, RiskContext
from app.risk.rules import (
    HARD_BLOCK_RULES,
    SCORE_RULES,
    _compat_breaking_change,
    _error_introduced,
    _hard_block_critical_compat_break,
    _hard_block_replay_failure_on_passing_baseline,
    _high_blast_radius,
    _new_replay_failure,
    _output_schema_break,
    _removed_required_step,
    _significant_latency_increase,
    _tool_invocation_changed,
)


def test_no_evidence_triggers_no_rule():
    ctx = RiskContext()
    for rule in SCORE_RULES + HARD_BLOCK_RULES:
        assert rule(ctx) is None


def test_compat_breaking_change_triggers_on_status():
    ctx = RiskContext(compatibility_status="breaking", compatibility_breaking_count=1)
    result = _compat_breaking_change(ctx)
    assert result is not None
    assert result.rule_id == "COMPAT_BREAKING_CHANGE"
    assert result.category is RiskCategory.COMPATIBILITY
    assert result.score_delta == 30


def test_compat_breaking_change_does_not_trigger_on_warning_status():
    ctx = RiskContext(compatibility_status="warning", compatibility_breaking_count=0)
    assert _compat_breaking_change(ctx) is None


def test_new_replay_failure_scales_and_caps():
    assert _new_replay_failure(RiskContext(new_failures=1)).score_delta == 15
    assert _new_replay_failure(RiskContext(new_failures=2)).score_delta == 30
    assert _new_replay_failure(RiskContext(new_failures=10)).score_delta == 45  # capped


def test_removed_required_step_requires_flag():
    assert _removed_required_step(RiskContext(removed_steps=1)) is None
    result = _removed_required_step(RiskContext(has_removed_required_step=True))
    assert result is not None
    assert result.rule_id == "REMOVED_REQUIRED_STEP"


def test_high_blast_radius_bands():
    assert _high_blast_radius(RiskContext(blast_radius_total_affected=None)) is None
    assert _high_blast_radius(RiskContext(blast_radius_total_affected=0)) is None
    assert _high_blast_radius(RiskContext(blast_radius_total_affected=2)) is None
    moderate = _high_blast_radius(RiskContext(blast_radius_total_affected=3))
    assert moderate is not None and moderate.score_delta == 10
    high = _high_blast_radius(RiskContext(blast_radius_total_affected=10))
    assert high is not None and high.score_delta == 20


def test_output_schema_break():
    assert _output_schema_break(RiskContext(schema_changes=0)) is None
    result = _output_schema_break(RiskContext(schema_changes=1))
    assert result is not None and result.score_delta == 20


def test_tool_invocation_changed():
    assert _tool_invocation_changed(RiskContext(tool_invocation_changed=False)) is None
    result = _tool_invocation_changed(RiskContext(tool_invocation_changed=True))
    assert result is not None and result.score_delta == 10


def test_error_introduced():
    assert _error_introduced(RiskContext(error_introduced=False)) is None
    result = _error_introduced(RiskContext(error_introduced=True))
    assert result is not None and result.score_delta == 15


def test_significant_latency_increase_threshold():
    assert _significant_latency_increase(RiskContext(max_latency_percent_delta=49.9)) is None
    result = _significant_latency_increase(RiskContext(max_latency_percent_delta=50.0))
    assert result is not None and result.score_delta == 10


def test_resolved_failure_alone_triggers_nothing():
    # spec §11: "failure resolved must NOT increase risk" — there is no
    # rule keyed on `resolved_failures` at all.
    ctx = RiskContext(resolved_failures=5)
    for rule in SCORE_RULES:
        assert rule(ctx) is None


def test_hard_block_critical_compat_break():
    assert _hard_block_critical_compat_break(RiskContext(compatibility_critical_count=0)) is None
    result = _hard_block_critical_compat_break(RiskContext(compatibility_critical_count=1))
    assert result is not None
    assert result.hard_block is True
    assert result.score_delta == 0


def test_hard_block_replay_failure_on_passing_baseline():
    assert _hard_block_replay_failure_on_passing_baseline(RiskContext(new_failures=0)) is None
    result = _hard_block_replay_failure_on_passing_baseline(RiskContext(new_failures=1))
    assert result is not None
    assert result.hard_block is True
    assert result.score_delta == 0


def test_evidence_refs_never_empty_when_triggered():
    ctx = RiskContext(
        compatibility_status="breaking",
        compatibility_breaking_count=1,
        compatibility_critical_count=1,
        new_failures=1,
        has_removed_required_step=True,
        blast_radius_total_affected=15,
        schema_changes=1,
        tool_invocation_changed=True,
        error_introduced=True,
        max_latency_percent_delta=99.0,
    )
    for rule in SCORE_RULES + HARD_BLOCK_RULES:
        result = rule(ctx)
        assert result is not None
        assert len(result.evidence_refs) > 0, result.rule_id
