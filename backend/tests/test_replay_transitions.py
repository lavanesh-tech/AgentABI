"""Pure unit tests for `app/replay/transitions.py`. No database, no I/O."""

from app.replay.models import ReplayStatus
from app.replay.transitions import is_terminal, is_valid_transition


def test_pending_to_running_is_valid():
    assert is_valid_transition(ReplayStatus.PENDING, ReplayStatus.RUNNING)


def test_pending_to_failed_is_valid():
    assert is_valid_transition(ReplayStatus.PENDING, ReplayStatus.FAILED)


def test_running_to_completed_is_valid():
    assert is_valid_transition(ReplayStatus.RUNNING, ReplayStatus.COMPLETED)


def test_running_to_failed_is_valid():
    assert is_valid_transition(ReplayStatus.RUNNING, ReplayStatus.FAILED)


def test_pending_to_completed_is_invalid():
    assert not is_valid_transition(ReplayStatus.PENDING, ReplayStatus.COMPLETED)


def test_completed_to_running_is_invalid():
    assert not is_valid_transition(ReplayStatus.COMPLETED, ReplayStatus.RUNNING)


def test_failed_to_completed_is_invalid():
    assert not is_valid_transition(ReplayStatus.FAILED, ReplayStatus.COMPLETED)


def test_running_to_pending_is_invalid():
    assert not is_valid_transition(ReplayStatus.RUNNING, ReplayStatus.PENDING)


def test_terminal_statuses():
    assert is_terminal(ReplayStatus.COMPLETED)
    assert is_terminal(ReplayStatus.FAILED)
    assert not is_terminal(ReplayStatus.PENDING)
    assert not is_terminal(ReplayStatus.RUNNING)
