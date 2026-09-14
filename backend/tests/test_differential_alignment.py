"""Pure unit tests for deterministic step alignment (spec §7/§27/§28)."""

import uuid

from app.differential.alignment import align_steps
from app.differential.models import AlignmentMethod, ReplayStepView

COMPONENT = uuid.uuid4()
VERSION_A = uuid.uuid4()
VERSION_B = uuid.uuid4()


def _step(
    seq: int, event_id: uuid.UUID | None = None, component_id=None, **kwargs
) -> ReplayStepView:
    return ReplayStepView(
        id=uuid.uuid4(),
        sequence_number=seq,
        source_event_id=event_id or uuid.uuid4(),
        kind=kwargs.get("kind", "reused_evidence"),
        status=kwargs.get("status", "reused"),
        component_id=component_id,
        component_version_id=kwargs.get("component_version_id"),
        input=kwargs.get("input"),
        output=kwargs.get("output"),
        error=kwargs.get("error"),
        duration_ms=kwargs.get("duration_ms"),
    )


def test_matched_by_source_event_id():
    event = uuid.uuid4()
    b = _step(0, event_id=event)
    c = _step(0, event_id=event)
    pairs = align_steps([b], [c])
    assert len(pairs) == 1
    assert pairs[0].method == AlignmentMethod.SOURCE_EVENT_ID
    assert pairs[0].baseline is b
    assert pairs[0].candidate is c


def test_added_step_candidate_only():
    b = _step(0)
    c1 = _step(0)
    c2 = _step(1)
    pairs = align_steps([b], [c1, c2])
    added = [p for p in pairs if p.baseline is None]
    assert len(added) == 1


def test_removed_step_baseline_only():
    b1 = _step(0)
    b2 = _step(1)
    c = _step(0)
    pairs = align_steps([b1, b2], [c])
    removed = [p for p in pairs if p.candidate is None]
    assert len(removed) == 1


def test_fallback_to_sequence_number_across_different_trajectories():
    b = _step(0)  # distinct random event_id
    c = _step(0)  # distinct random event_id, different trajectory
    pairs = align_steps([b], [c])
    assert len(pairs) == 1
    assert pairs[0].method == AlignmentMethod.SEQUENCE_NUMBER


def test_fallback_to_component_identity():
    # Different sequence numbers and event ids, same component — only
    # reachable via pass 3.
    b = _step(0, component_id=COMPONENT)
    c = _step(5, component_id=COMPONENT)
    pairs = align_steps([b], [c])
    assert len(pairs) == 1
    assert pairs[0].method == AlignmentMethod.COMPONENT_IDENTITY


def test_deterministic_ordering_stable_across_runs():
    event = uuid.uuid4()
    baseline = [_step(2, event_id=event), _step(0), _step(1)]
    candidate = [_step(0), _step(1), _step(2, event_id=event)]
    first = align_steps(baseline, candidate)
    second = align_steps(baseline, candidate)
    assert [p.sort_key for p in first] == [p.sort_key for p in second]
    assert [p.sort_key for p in first] == sorted(p.sort_key for p in first)


def test_empty_baseline_and_candidate():
    assert align_steps([], []) == []


def test_empty_baseline_all_added():
    c = [_step(0), _step(1)]
    pairs = align_steps([], c)
    assert len(pairs) == 2
    assert all(p.baseline is None for p in pairs)


def test_duplicate_ambiguous_sequence_numbers_deterministic():
    # Two baseline steps share sequence_number 0 (shouldn't happen in
    # practice — replay_steps has a unique constraint — but the
    # alignment must still behave deterministically, never crash).
    b1 = _step(0)
    b2 = _step(0)
    c1 = _step(0)
    pairs = align_steps([b1, b2], [c1])
    # Exactly one match by sequence_number (first-seen wins), the other
    # baseline step is unmatched (removed).
    matched = [p for p in pairs if p.baseline is not None and p.candidate is not None]
    removed = [p for p in pairs if p.candidate is None]
    assert len(matched) == 1
    assert len(removed) == 1
