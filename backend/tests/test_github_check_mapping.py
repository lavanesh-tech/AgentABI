"""Pure unit tests for `app/github/check_mapping.py` (Phase 12 spec §12-
§16). No `httpx`/SQLAlchemy import in `app.github.check_mapping`, so this
runs for real via `pytest --noconftest`.
"""

from app.github.check_mapping import (
    CHECK_NAME,
    build_completed_output,
    build_in_progress_output,
    decision_to_conclusion,
)
from app.github.checks_models import CheckConclusion
from app.risk.models import RiskDecision


def test_decision_to_conclusion_is_total_over_every_risk_decision():
    for decision in RiskDecision:
        # Must not raise KeyError for any current member.
        decision_to_conclusion(decision)


def test_pass_maps_to_success():
    assert decision_to_conclusion(RiskDecision.PASS) is CheckConclusion.SUCCESS


def test_warn_maps_to_neutral():
    assert decision_to_conclusion(RiskDecision.WARN) is CheckConclusion.NEUTRAL


def test_block_maps_to_failure():
    assert decision_to_conclusion(RiskDecision.BLOCK) is CheckConclusion.FAILURE


def test_check_name_is_stable_and_centralized():
    assert CHECK_NAME == "AgentABI Compatibility"


def test_in_progress_output_mentions_pipeline_running():
    output = build_in_progress_output(compatibility_summary=None)
    assert "AgentABI" in output.title
    assert "running" in output.summary.lower()


def test_in_progress_output_includes_compatibility_summary_when_given():
    output = build_in_progress_output(compatibility_summary="3 change(s), all compatible.")
    assert "3 change(s)" in output.summary


def test_pass_summary_never_claims_zero_risk():
    output = build_completed_output(
        decision=RiskDecision.PASS,
        score=5,
        risk_engine_version="1",
        hard_block=False,
        top_rules=[],
    )
    assert "zero risk" not in output.summary.lower()
    assert "no risk" not in output.summary.lower()
    assert "threshold was exceeded" in output.summary
    assert "AgentABI decision: PASS" in output.title


def test_warn_summary_explicitly_states_warn_decision():
    output = build_completed_output(
        decision=RiskDecision.WARN,
        score=45,
        risk_engine_version="1",
        hard_block=False,
        top_rules=[("NEW_REPLAY_FAILURE", 15)],
    )
    assert "AgentABI decision: WARN" in output.summary
    assert "AgentABI decision: WARN" in output.title


def test_warn_summary_is_distinct_from_pass_summary():
    pass_output = build_completed_output(
        decision=RiskDecision.PASS,
        score=5,
        risk_engine_version="1",
        hard_block=False,
        top_rules=[],
    )
    warn_output = build_completed_output(
        decision=RiskDecision.WARN,
        score=45,
        risk_engine_version="1",
        hard_block=False,
        top_rules=[],
    )
    assert pass_output.summary != warn_output.summary
    assert pass_output.title != warn_output.title


def test_block_summary_identifies_score_and_hard_block():
    output = build_completed_output(
        decision=RiskDecision.BLOCK,
        score=95,
        risk_engine_version="1",
        hard_block=True,
        top_rules=[("HARD_BLOCK_REPLAY_FAILURE_ON_PASSING_BASELINE", 100)],
    )
    assert "AgentABI decision: BLOCK" in output.summary
    assert "95/100" in output.summary
    assert "Hard block" in output.summary
    assert "HARD_BLOCK_REPLAY_FAILURE_ON_PASSING_BASELINE" in output.summary


def test_top_rules_truncated_to_five():
    top_rules = [(f"RULE_{i}", i) for i in range(10)]
    output = build_completed_output(
        decision=RiskDecision.WARN,
        score=50,
        risk_engine_version="1",
        hard_block=False,
        top_rules=top_rules,
    )
    for rule_id, _ in top_rules[:5]:
        assert rule_id in output.summary
    for rule_id, _ in top_rules[5:]:
        assert rule_id not in output.summary


def test_completed_output_includes_optional_sections_only_when_given():
    bare = build_completed_output(
        decision=RiskDecision.PASS,
        score=0,
        risk_engine_version="1",
        hard_block=False,
        top_rules=[],
    )
    assert "Compatibility:" not in bare.summary
    assert "Differential:" not in bare.summary
    assert "Explanation:" not in bare.summary

    full = build_completed_output(
        decision=RiskDecision.PASS,
        score=0,
        risk_engine_version="1",
        hard_block=False,
        top_rules=[],
        compatibility_summary="2 change(s), all compatible.",
        differential_summary="no regressions detected.",
        report_url="https://agentabi.example/reports/abc",
        explanation="This change looks safe based on the deterministic evidence.",
    )
    assert "**Compatibility:** 2 change(s), all compatible." in full.summary
    assert "**Differential:** no regressions detected." in full.summary
    assert "**Explanation:**" in full.summary
    assert "[Full AgentABI report](https://agentabi.example/reports/abc)" in full.summary
