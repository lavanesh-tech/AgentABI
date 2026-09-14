"""Pure unit tests for `app.differential.analyzer.analyze` (spec §27/§28)
— the end-to-end deterministic comparison, no database, no LLM."""

import uuid

from app.differential.analyzer import analyze
from app.differential.models import DifferenceType, ReplayStepView


def _step(seq: int, event_id=None, **kwargs) -> ReplayStepView:
    return ReplayStepView(
        id=uuid.uuid4(),
        sequence_number=seq,
        source_event_id=event_id or uuid.uuid4(),
        kind=kwargs.get("kind", "reused_evidence"),
        status=kwargs.get("status", "reused"),
        component_id=kwargs.get("component_id"),
        component_version_id=kwargs.get("component_version_id"),
        input=kwargs.get("input"),
        output=kwargs.get("output"),
        error=kwargs.get("error"),
        duration_ms=kwargs.get("duration_ms"),
    )


def test_identical_replays_produce_no_differences():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, output={"x": 1})]
    c = [_step(0, event_id=event, output={"x": 1})]
    report = analyze(b, c)
    assert report.summary.matched_steps == 1
    assert report.summary.changed_steps == 0
    assert report.total_differences == 0


def test_added_step_summary():
    b = [_step(0)]
    c = [_step(0), _step(1)]
    report = analyze(b, c)
    assert report.summary.added_steps == 1
    assert any(DifferenceType.STEP_ADDED in sd.difference_types for sd in report.step_differences)


def test_removed_step_summary():
    b = [_step(0), _step(1)]
    c = [_step(0)]
    report = analyze(b, c)
    assert report.summary.removed_steps == 1


def test_status_changed():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, status="reused")]
    c = [_step(0, event_id=event, status="executed")]
    report = analyze(b, c)
    sd = report.step_differences[0]
    assert DifferenceType.STEP_STATUS_CHANGED in sd.difference_types


def test_provider_invocation_kind_changed():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, kind="reused_evidence")]
    c = [_step(0, event_id=event, kind="provider_execution_required")]
    report = analyze(b, c)
    assert DifferenceType.PROVIDER_INVOCATION_CHANGED in report.step_differences[0].difference_types


def test_tool_changed():
    event = uuid.uuid4()
    v1, v2 = uuid.uuid4(), uuid.uuid4()
    b = [_step(0, event_id=event, component_version_id=v1)]
    c = [_step(0, event_id=event, component_version_id=v2)]
    report = analyze(b, c)
    assert DifferenceType.TOOL_CHANGED in report.step_differences[0].difference_types


def test_output_scalar_changed():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, output=1)]
    c = [_step(0, event_id=event, output=2)]
    report = analyze(b, c)
    sd = report.step_differences[0]
    assert DifferenceType.OUTPUT_CHANGED in sd.difference_types
    assert report.summary.changed_outputs == 1


def test_nested_json_output_changed():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, output={"nested": {"x": 1}})]
    c = [_step(0, event_id=event, output={"nested": {"x": 2}})]
    report = analyze(b, c)
    assert report.summary.changed_outputs == 1


def test_error_introduced():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, error=None)]
    c = [_step(0, event_id=event, error={"category": "TimeoutError"})]
    report = analyze(b, c)
    sd = report.step_differences[0]
    assert sd.error_difference.difference_type == DifferenceType.ERROR_INTRODUCED
    assert report.summary.new_failures == 1


def test_error_resolved():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, error={"category": "TimeoutError"})]
    c = [_step(0, event_id=event, error=None)]
    report = analyze(b, c)
    sd = report.step_differences[0]
    assert sd.error_difference.difference_type == DifferenceType.ERROR_RESOLVED
    assert report.summary.resolved_failures == 1


def test_error_category_changed():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, error={"category": "TimeoutError"})]
    c = [_step(0, event_id=event, error={"category": "ValueError"})]
    report = analyze(b, c)
    assert (
        report.step_differences[0].error_difference.difference_type == DifferenceType.ERROR_CHANGED
    )


def test_latency_delta_computed_only_with_real_measurements():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, duration_ms=100)]
    c = [_step(0, event_id=event, duration_ms=150)]
    report = analyze(b, c)
    latency = report.step_differences[0].latency_difference
    assert latency.delta_ms == 50
    assert latency.percent_delta == 50.0


def test_latency_not_computed_when_missing_on_either_side():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, duration_ms=None)]
    c = [_step(0, event_id=event, duration_ms=100)]
    report = analyze(b, c)
    assert report.step_differences[0].latency_difference is None


def test_tool_changed_via_component_id():
    comp_a, comp_b = uuid.uuid4(), uuid.uuid4()
    event = uuid.uuid4()
    b = [_step(0, event_id=event, component_id=comp_a)]
    c = [_step(0, event_id=event, component_id=comp_b)]
    report = analyze(b, c)
    assert DifferenceType.TOOL_CHANGED in report.step_differences[0].difference_types


def test_summary_metrics_totals():
    b = [_step(i) for i in range(3)]
    c = [_step(i) for i in range(2)]
    report = analyze(b, c)
    assert report.summary.total_baseline_steps == 3
    assert report.summary.total_candidate_steps == 2


def test_deterministic_ordering_across_runs():
    events = [uuid.uuid4() for _ in range(5)]
    baseline = [_step(i, event_id=events[i], output=i) for i in range(5)]
    candidate = [_step(i, event_id=events[i], output=i + 1) for i in range(5)]
    first = analyze(baseline, candidate)
    second = analyze(baseline, candidate)
    assert [sd.sequence_number for sd in first.step_differences] == [
        sd.sequence_number for sd in second.step_differences
    ]


def test_analyzer_version_is_recorded():
    report = analyze([], [])
    assert report.analyzer_version == "1"


def test_empty_baseline_and_candidate():
    report = analyze([], [])
    assert report.total_differences == 0
    assert report.summary.total_baseline_steps == 0
    assert report.summary.total_candidate_steps == 0


def test_null_output_vs_missing_distinguishable():
    event = uuid.uuid4()
    b = [_step(0, event_id=event, output=None)]
    c = [_step(0, event_id=event, output={"x": 1})]
    report = analyze(b, c)
    assert DifferenceType.OUTPUT_CHANGED in report.step_differences[0].difference_types
