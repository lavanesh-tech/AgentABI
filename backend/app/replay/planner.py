"""Deterministic replay-plan construction (Phase 7 §3/§5/§7). Pure
function: same events + same baseline/candidate always produce the same
plan, in `sequence_number` order, never relying on timestamps or
insertion order. Never mutates its inputs — the source trajectory's
events are only read.

Classification rules:
- An invocation event (`TOOL_CALL`/`MCP_REQUEST`/`API_REQUEST`) whose
  `component_id`/`component_version_id` match the baseline being
  replaced -> `SUBSTITUTED_EXECUTION` (re-run with the candidate).
- Its paired response event (matched by `invocation_id` for tool events,
  or simply the next response in sequence for MCP/API) ->
  `SKIPPED`, justified as superseded by the substituted execution — its
  historical content described a run against the baseline, not the
  candidate, so keeping it as the step's evidence would misrepresent
  what the replay actually did.
- Any other invocation/response event (a different component
  entirely) -> `REUSED_EVIDENCE` — historical evidence retained as-is,
  not re-executed (Phase 7 §7's "historical result retained only as
  baseline evidence").
- `MODEL_REQUEST`/`MODEL_RESPONSE` -> `PROVIDER_EXECUTION_REQUIRED`:
  Phase 7 must not fabricate a model response; a real provider adapter
  doesn't exist until Phase 8/9.
- Everything else (`RUN_STARTED`, `AGENT_STARTED`, `AGENT_COMPLETED`,
  `STATE_READ`, `STATE_WRITE`, `DECISION`, `STRUCTURED_OUTPUT`, `ERROR`,
  and any unmatched response) -> `REUSED_EVIDENCE`.
"""

from typing import Any

from app.domain.exceptions import InvalidReplaySubstitution
from app.replay.models import ReplayPlan, ReplayPlanStep, StepKind, TrajectoryEventView
from app.trajectory.models import EventType

_INVOCATION_TYPES = frozenset({EventType.TOOL_CALL, EventType.MCP_REQUEST, EventType.API_REQUEST})
_RESPONSE_TYPES = frozenset(
    {EventType.TOOL_RESPONSE, EventType.MCP_RESPONSE, EventType.API_RESPONSE}
)
_PROVIDER_TYPES = frozenset({EventType.MODEL_REQUEST, EventType.MODEL_RESPONSE})


def _invocation_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("invocation_id")
        return value if isinstance(value, str) else None
    return None


def build_replay_plan(
    events: list[TrajectoryEventView],
    *,
    baseline_component_id: Any,
    baseline_version_id: Any,
    candidate_version_id: Any,
) -> ReplayPlan:
    ordered = sorted(events, key=lambda e: e.sequence_number)
    substituted_invocation_ids: set[str] = set()
    steps: list[ReplayPlanStep] = []

    for event in ordered:
        if (
            event.event_type in _INVOCATION_TYPES
            and event.component_id == baseline_component_id
            and event.component_version_id == baseline_version_id
        ):
            kind = StepKind.SUBSTITUTED_EXECUTION
            execution_version_id = candidate_version_id
            justification = None
            inv_id = _invocation_id(event.input)
            if inv_id is not None:
                substituted_invocation_ids.add(inv_id)
        elif (
            event.event_type in _RESPONSE_TYPES
            and _invocation_id(event.input) in substituted_invocation_ids
        ):
            kind = StepKind.SKIPPED
            execution_version_id = None
            justification = "superseded by substituted execution of its originating invocation"
        elif event.event_type in _PROVIDER_TYPES:
            kind = StepKind.PROVIDER_EXECUTION_REQUIRED
            execution_version_id = None
            justification = "model/provider execution requires an adapter (Phase 8/9)"
        else:
            kind = StepKind.REUSED_EVIDENCE
            execution_version_id = event.component_version_id
            justification = None

        steps.append(
            ReplayPlanStep(
                source_event_id=event.id,
                sequence_number=event.sequence_number,
                event_type=event.event_type,
                kind=kind,
                component_id=baseline_component_id
                if kind == StepKind.SUBSTITUTED_EXECUTION
                else event.component_id,
                execution_component_version_id=execution_version_id,
                historical_input=event.input,
                historical_output=event.output,
                justification=justification,
            )
        )

    plan = ReplayPlan(steps=tuple(steps))
    if not plan.substituted_steps():
        raise InvalidReplaySubstitution(
            "source trajectory does not contain any invocation of the baseline "
            "component version being replaced"
        )
    return plan
