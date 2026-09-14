"""Deterministic replay status-transition rules — the one place PENDING/
RUNNING/COMPLETED/FAILED rules live (Phase 7 §2), mirroring
`app/trajectory/transitions.py`."""

from app.replay.models import ReplayStatus

_VALID_TRANSITIONS: dict[ReplayStatus, frozenset[ReplayStatus]] = {
    ReplayStatus.PENDING: frozenset({ReplayStatus.RUNNING, ReplayStatus.FAILED}),
    ReplayStatus.RUNNING: frozenset({ReplayStatus.COMPLETED, ReplayStatus.FAILED}),
    ReplayStatus.COMPLETED: frozenset(),
    ReplayStatus.FAILED: frozenset(),
}

TERMINAL_STATUSES: frozenset[ReplayStatus] = frozenset(
    {ReplayStatus.COMPLETED, ReplayStatus.FAILED}
)


def is_valid_transition(current: ReplayStatus, target: ReplayStatus) -> bool:
    return target in _VALID_TRANSITIONS.get(current, frozenset())


def is_terminal(status: ReplayStatus) -> bool:
    return status in TERMINAL_STATUSES
