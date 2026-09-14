"""`DifferentialAnalyzer` — the pure, deterministic comparison engine
(spec §2/§3/§18). Takes two lists of `ReplayStepView` in, returns one
`DifferentialReport` out; no I/O, no randomness, no LLM call anywhere in
this module (see `tests/test_differential_no_llm_dependency.py`).
"""

from app.differential.alignment import StepPair, align_steps
from app.differential.models import (
    AlignmentMethod,
    DifferenceType,
    DifferentialReport,
    DifferentialSummary,
    ErrorDifference,
    LatencyDifference,
    ReplayStepView,
    StepDifference,
)
from app.differential.value_diff import diff_values
from app.trajectory.redaction import sanitize

ANALYZER_VERSION = "1"

_FAILURE_STATUSES = frozenset({"failed"})


def analyze(
    baseline_steps: list[ReplayStepView], candidate_steps: list[ReplayStepView]
) -> DifferentialReport:
    pairs = align_steps(baseline_steps, candidate_steps)
    step_diffs = [_diff_pair(pair) for pair in pairs]
    summary = _summarize(len(baseline_steps), len(candidate_steps), step_diffs)
    return DifferentialReport(
        analyzer_version=ANALYZER_VERSION,
        step_differences=tuple(step_diffs),
        summary=summary,
    )


def _diff_pair(pair: StepPair) -> StepDifference:
    b, c = pair.baseline, pair.candidate

    if b is None:
        return StepDifference(
            alignment_method=pair.method,
            difference_types=(DifferenceType.STEP_ADDED,),
            sequence_number=c.sequence_number,
            baseline=None,
            candidate=c,
        )
    if c is None:
        return StepDifference(
            alignment_method=pair.method,
            difference_types=(DifferenceType.STEP_REMOVED,),
            sequence_number=b.sequence_number,
            baseline=b,
            candidate=None,
        )

    types: list[DifferenceType] = []

    if b.status != c.status:
        types.append(DifferenceType.STEP_STATUS_CHANGED)
    if b.kind != c.kind:
        types.append(DifferenceType.PROVIDER_INVOCATION_CHANGED)
    if b.component_id != c.component_id or b.component_version_id != c.component_version_id:
        types.append(DifferenceType.TOOL_CHANGED)

    input_diffs = diff_values(b.input, c.input, path="$.input")
    if input_diffs:
        types.append(DifferenceType.INPUT_CHANGED)

    output_diffs = diff_values(b.output, c.output, path="$.output")
    if output_diffs:
        types.append(DifferenceType.OUTPUT_CHANGED)
        if any(d.difference_type == DifferenceType.SCHEMA_CHANGED for d in output_diffs):
            types.append(DifferenceType.SCHEMA_CHANGED)

    error_diff = _diff_errors(b, c)
    if error_diff is not None:
        types.append(error_diff.difference_type)

    latency_diff = _diff_latency(b, c)
    if latency_diff is not None:
        types.append(DifferenceType.LATENCY_CHANGED)

    return StepDifference(
        alignment_method=pair.method,
        difference_types=tuple(types),
        sequence_number=b.sequence_number,
        baseline=b,
        candidate=c,
        output_differences=tuple(input_diffs) + tuple(output_diffs),
        error_difference=error_diff,
        latency_difference=latency_diff,
    )


def _diff_errors(b: ReplayStepView, c: ReplayStepView) -> ErrorDifference | None:
    b_present = b.error is not None
    c_present = c.error is not None
    b_category = _error_category(b.error)
    c_category = _error_category(c.error)

    if not b_present and not c_present:
        return None
    if b_present and not c_present:
        return ErrorDifference(
            difference_type=DifferenceType.ERROR_RESOLVED,
            baseline_present=True,
            candidate_present=False,
            baseline_category=b_category,
        )
    if not b_present and c_present:
        return ErrorDifference(
            difference_type=DifferenceType.ERROR_INTRODUCED,
            baseline_present=False,
            candidate_present=True,
            candidate_category=c_category,
        )
    if b_category != c_category:
        return ErrorDifference(
            difference_type=DifferenceType.ERROR_CHANGED,
            baseline_present=True,
            candidate_present=True,
            baseline_category=b_category,
            candidate_category=c_category,
        )
    return None


def _error_category(error) -> str | None:
    """Never returns a raw stack trace or secret (spec §13) — only a
    sanitized, safe category label."""

    if error is None:
        return None
    if isinstance(error, dict):
        sanitized = sanitize(error)
        category = sanitized.get("category") or sanitized.get("type") or sanitized.get("code")
        return str(category) if category is not None else "unknown"
    return "unknown"


def _diff_latency(b: ReplayStepView, c: ReplayStepView) -> LatencyDifference | None:
    if b.duration_ms is None or c.duration_ms is None:
        return None
    delta = c.duration_ms - b.duration_ms
    if delta == 0:
        return None
    percent = (delta / b.duration_ms * 100.0) if b.duration_ms > 0 else None
    return LatencyDifference(
        baseline_duration_ms=b.duration_ms,
        candidate_duration_ms=c.duration_ms,
        delta_ms=delta,
        percent_delta=percent,
    )


def _summarize(
    total_baseline: int, total_candidate: int, step_diffs: list[StepDifference]
) -> DifferentialSummary:
    matched = added = removed = changed = 0
    new_failures = resolved_failures = changed_outputs = schema_changes = 0

    for sd in step_diffs:
        if sd.alignment_method == AlignmentMethod.UNMATCHED:
            if sd.baseline is None:
                added += 1
            else:
                removed += 1
            continue
        matched += 1
        if sd.difference_types:
            changed += 1
        if DifferenceType.OUTPUT_CHANGED in sd.difference_types:
            changed_outputs += 1
        if DifferenceType.SCHEMA_CHANGED in sd.difference_types:
            schema_changes += 1
        if sd.error_difference is not None:
            if sd.error_difference.difference_type == DifferenceType.ERROR_INTRODUCED:
                new_failures += 1
            elif sd.error_difference.difference_type == DifferenceType.ERROR_RESOLVED:
                resolved_failures += 1

    return DifferentialSummary(
        total_baseline_steps=total_baseline,
        total_candidate_steps=total_candidate,
        matched_steps=matched,
        added_steps=added,
        removed_steps=removed,
        changed_steps=changed,
        new_failures=new_failures,
        resolved_failures=resolved_failures,
        changed_outputs=changed_outputs,
        schema_changes=schema_changes,
    )
