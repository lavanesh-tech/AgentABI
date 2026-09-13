"""Centralized trajectory status transition rules (Phase 6 §12). The only
two valid transitions are RUNNING -> COMPLETED and RUNNING -> FAILED;
every terminal-to-anything transition (including re-completing/re-failing
an already-terminal trajectory) is rejected. Nothing outside this module
decides whether a transition is legal — `TrajectoryRecorderService` calls
`is_valid_transition`, never re-implements the rule."""

from app.trajectory.models import TrajectoryStatus

_VALID_TRANSITIONS: dict[TrajectoryStatus, frozenset[TrajectoryStatus]] = {
    TrajectoryStatus.RUNNING: frozenset({TrajectoryStatus.COMPLETED, TrajectoryStatus.FAILED}),
}

TERMINAL_STATUSES: frozenset[TrajectoryStatus] = frozenset(
    {TrajectoryStatus.COMPLETED, TrajectoryStatus.FAILED}
)


def is_valid_transition(current: TrajectoryStatus, target: TrajectoryStatus) -> bool:
    return target in _VALID_TRANSITIONS.get(current, frozenset())


def is_terminal(status: TrajectoryStatus) -> bool:
    return status in TERMINAL_STATUSES
