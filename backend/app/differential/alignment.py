"""Deterministic step alignment (spec §7) — never an LLM. Fallback
hierarchy, applied in order, each pass only considering steps neither
side has already matched:

1. `source_event_id` — exact match. If baseline and candidate replay
   the same source trajectory (the common case: same historical run,
   different candidate component version), every step shares its
   source event id across both runs, giving a perfect 1:1 alignment.
2. `sequence_number` — exact match, for steps two *different*
   trajectories' replays can't share an event id for.
3. `component_identity` — same `component_id`, matched in ascending
   `sequence_number` order on each side (first-available deterministic
   pairing, never a fuzzy/best-effort match).
4. Whatever is left is unmatched: baseline-only becomes `STEP_REMOVED`,
   candidate-only becomes `STEP_ADDED` (spec §8).
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.differential.models import AlignmentMethod, ReplayStepView


@dataclass(frozen=True, slots=True)
class StepPair:
    method: AlignmentMethod
    baseline: ReplayStepView | None
    candidate: ReplayStepView | None

    @property
    def sort_key(self) -> tuple[int, int]:
        # Baseline sequence takes priority for ordering; a candidate-only
        # step sorts by its own sequence number. Deterministic and
        # stable across runs (spec §33).
        if self.baseline is not None:
            return (0, self.baseline.sequence_number)
        assert self.candidate is not None
        return (1, self.candidate.sequence_number)


def align_steps(baseline: list[ReplayStepView], candidate: list[ReplayStepView]) -> list[StepPair]:
    remaining_baseline = {step.id: step for step in baseline}
    remaining_candidate = {step.id: step for step in candidate}
    pairs: list[StepPair] = []

    # Pass 1: source_event_id
    baseline_by_event = _index(remaining_baseline.values(), key=lambda s: s.source_event_id)
    candidate_by_event = _index(remaining_candidate.values(), key=lambda s: s.source_event_id)
    for event_id in sorted(set(baseline_by_event) & set(candidate_by_event), key=str):
        b = baseline_by_event[event_id]
        c = candidate_by_event[event_id]
        pairs.append(StepPair(AlignmentMethod.SOURCE_EVENT_ID, b, c))
        del remaining_baseline[b.id]
        del remaining_candidate[c.id]

    # Pass 2: sequence_number
    baseline_by_seq = _index(remaining_baseline.values(), key=lambda s: s.sequence_number)
    candidate_by_seq = _index(remaining_candidate.values(), key=lambda s: s.sequence_number)
    for seq in sorted(set(baseline_by_seq) & set(candidate_by_seq)):
        b = baseline_by_seq[seq]
        c = candidate_by_seq[seq]
        pairs.append(StepPair(AlignmentMethod.SEQUENCE_NUMBER, b, c))
        del remaining_baseline[b.id]
        del remaining_candidate[c.id]

    # Pass 3: component_identity — first-available pairing in ascending
    # sequence order per component_id, deterministic even with repeats.
    b_by_component = _group_by_component(remaining_baseline.values())
    c_by_component = _group_by_component(remaining_candidate.values())
    for component_id in sorted(set(b_by_component) & set(c_by_component), key=str):
        b_list = b_by_component[component_id]
        c_list = c_by_component[component_id]
        for b, c in zip(b_list, c_list, strict=False):
            pairs.append(StepPair(AlignmentMethod.COMPONENT_IDENTITY, b, c))
            del remaining_baseline[b.id]
            del remaining_candidate[c.id]

    # Pass 4: unmatched
    for step in remaining_baseline.values():
        pairs.append(StepPair(AlignmentMethod.UNMATCHED, step, None))
    for step in remaining_candidate.values():
        pairs.append(StepPair(AlignmentMethod.UNMATCHED, None, step))

    pairs.sort(key=lambda p: p.sort_key)
    return pairs


def _index[K](
    steps: Iterable[ReplayStepView], *, key: Callable[[ReplayStepView], K]
) -> dict[K, ReplayStepView]:
    result: dict[K, ReplayStepView] = {}
    for step in steps:
        k = key(step)
        if k not in result:  # first-seen wins — deterministic, no overwrite churn
            result[k] = step
    return result


def _group_by_component(
    steps: Iterable[ReplayStepView],
) -> dict[uuid.UUID, list[ReplayStepView]]:
    groups: dict[uuid.UUID, list[ReplayStepView]] = {}
    for step in sorted(steps, key=lambda s: s.sequence_number):
        if step.component_id is None:
            continue
        groups.setdefault(step.component_id, []).append(step)
    return groups
