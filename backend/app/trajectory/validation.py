"""Event-shape invariants (Phase 6 §23) — deliberately minimal: enough to
reject nonsensical events, not a full schema per event type. Anything
requiring database access (component-version project scoping) is *not*
here — that's `TrajectoryRecorderService`'s job; this module is pure and
independently testable.
"""

from app.domain.exceptions import InvalidTrajectoryEvent
from app.trajectory.models import EventType

# These describe a trajectory-level status transition and must go through
# `TrajectoryRecorderService.complete_trajectory`/`fail_trajectory`, never
# a generic `append_event` call — recording them as an ordinary event
# would let a trajectory's terminal status and its event log disagree.
RESERVED_EVENT_TYPES: frozenset[EventType] = frozenset(
    {EventType.RUN_COMPLETED, EventType.RUN_FAILED}
)

_REQUIRES_INVOCATION_ID: frozenset[EventType] = frozenset(
    {EventType.TOOL_CALL, EventType.TOOL_RESPONSE}
)
_REQUIRES_STATE_KEY: frozenset[EventType] = frozenset({EventType.STATE_READ, EventType.STATE_WRITE})


def validate_event_shape(
    event_type: EventType,
    *,
    input_payload: object | None,
    error_payload: object | None,
) -> None:
    """Raises `InvalidTrajectoryEvent` if `event_type` combined with the
    given payloads is structurally nonsensical. Does not validate
    component-version references — see `TrajectoryRecorderService`."""

    if event_type in RESERVED_EVENT_TYPES:
        raise InvalidTrajectoryEvent(
            f"{event_type} must be recorded via complete_trajectory/fail_trajectory, "
            "not append_event"
        )

    if event_type in _REQUIRES_INVOCATION_ID:
        _require_input_key(event_type, input_payload, "invocation_id")

    if event_type in _REQUIRES_STATE_KEY:
        _require_input_key(event_type, input_payload, "key")

    if event_type == EventType.ERROR and error_payload is None:
        raise InvalidTrajectoryEvent("ERROR events require a non-null error payload")


def _require_input_key(event_type: EventType, input_payload: object | None, key: str) -> None:
    if not isinstance(input_payload, dict) or key not in input_payload:
        raise InvalidTrajectoryEvent(f"{event_type} events require '{key}' in their input payload")
