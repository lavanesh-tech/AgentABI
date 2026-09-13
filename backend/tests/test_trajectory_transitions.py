"""Pure unit tests for `app/trajectory/transitions.py`. No database, no
I/O."""

from app.trajectory.models import TrajectoryStatus
from app.trajectory.transitions import is_terminal, is_valid_transition


def test_running_to_completed_is_valid():
    assert is_valid_transition(TrajectoryStatus.RUNNING, TrajectoryStatus.COMPLETED) is True


def test_running_to_failed_is_valid():
    assert is_valid_transition(TrajectoryStatus.RUNNING, TrajectoryStatus.FAILED) is True


def test_completed_to_running_is_invalid():
    assert is_valid_transition(TrajectoryStatus.COMPLETED, TrajectoryStatus.RUNNING) is False


def test_failed_to_completed_is_invalid():
    assert is_valid_transition(TrajectoryStatus.FAILED, TrajectoryStatus.COMPLETED) is False


def test_completed_to_completed_is_invalid():
    assert is_valid_transition(TrajectoryStatus.COMPLETED, TrajectoryStatus.COMPLETED) is False


def test_failed_to_failed_is_invalid():
    assert is_valid_transition(TrajectoryStatus.FAILED, TrajectoryStatus.FAILED) is False


def test_running_to_running_is_invalid():
    assert is_valid_transition(TrajectoryStatus.RUNNING, TrajectoryStatus.RUNNING) is False


def test_terminal_statuses():
    assert is_terminal(TrajectoryStatus.COMPLETED) is True
    assert is_terminal(TrajectoryStatus.FAILED) is True
    assert is_terminal(TrajectoryStatus.RUNNING) is False
