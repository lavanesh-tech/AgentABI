"""Phase 16 spec §8/§38 (mandatory): `agentabi_risk_decisions_total` must
observe PASS/WARN/BLOCK exactly as `app.risk.engine.evaluate()` produced
them — this test asserts, via source inspection, that `RiskService.
run_assessment` calls `record_risk_decision(...)` with `record.decision`/
`record.hard_block`/`record.score` (the persisted result of
`_run_assessment_impl`, which is itself a pass-through of `evaluate()`'s
output — see app/risk/engine.py) and never recomputes or re-derives a
decision value anywhere in the metrics path. Needs SQLAlchemy/asyncpg/a
real Postgres session — none available in this sandbox this session
(PyPI unreachable — see docs/DECISIONS.md). Written and `py_compile`-
clean; not pytest-executed.
"""

import inspect

from app.services.risk_service import RiskService


def test_run_assessment_records_risk_decision_from_persisted_record_only():
    source = inspect.getsource(RiskService.run_assessment)
    assert "record_risk_decision" in source
    # Must be called with the already-persisted `record`'s own attributes
    # — not a locally recomputed value, not `assessment` (the pure
    # dataclass returned by app.risk.engine.evaluate before persistence).
    assert "decision=record.decision" in source
    assert "hard_block=record.hard_block" in source
    assert "score=record.score" in source


def test_run_assessment_never_computes_a_decision_itself():
    """The wrapper method that records metrics must not itself contain
    any risk-scoring logic — `evaluate()`/`app.risk.engine` remain the
    only place a decision is computed (spec §2's architectural
    invariant, unchanged by Phase 16)."""

    source = inspect.getsource(RiskService.run_assessment)
    assert "evaluate(" not in source
    assert "RiskContext(" not in source


def test_record_risk_decision_signature_takes_no_engine_inputs():
    """The metrics helper itself has no access to compatibility scans,
    differential reports, or blast-radius data — it can only observe a
    decision/hard_block/score that were already computed elsewhere,
    structurally preventing it from ever becoming a second place a
    decision could be produced."""

    from app.observability.metrics import record_risk_decision

    params = set(inspect.signature(record_risk_decision).parameters)
    assert params == {"settings", "decision", "hard_block", "score"}
