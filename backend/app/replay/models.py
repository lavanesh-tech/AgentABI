"""Pure domain model for deterministic replay — no SQLAlchemy/FastAPI/
Pydantic import here, same testability choice as `app/trajectory/models.py`
(Phase 6) and `app/compatibility/models.py` (Phase 5).

`ReplayStatus` is the replay run's own lifecycle; `StepKind` is *why* a
plan step was classified the way it was (decided once, at planning time,
by `app/replay/planner.py`); `StepStatus` is the resulting outcome
persisted per step — for every kind except `SUBSTITUTED_EXECUTION` the
status is a deterministic 1:1 mirror of the kind, decided without
calling anything; only a `SUBSTITUTED_EXECUTION` step's status depends on
what the executor actually returns.
"""

import enum
import uuid
from dataclasses import dataclass
from typing import Any

from app.trajectory.models import EventType


class ReplayStatus(enum.StrEnum):
    """PENDING -> RUNNING -> COMPLETED, or PENDING/RUNNING -> FAILED.
    Centralized in `app/replay/transitions.py`, never re-implemented per
    endpoint (mirrors Phase 6's `TrajectoryStatus`)."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StepKind(enum.StrEnum):
    """Why a historical event was classified this way by the planner —
    see `app/replay/planner.py` for the rules."""

    REUSED_EVIDENCE = "reused_evidence"
    SUBSTITUTED_EXECUTION = "substituted_execution"
    PROVIDER_EXECUTION_REQUIRED = "provider_execution_required"
    SKIPPED = "skipped"


class StepStatus(enum.StrEnum):
    """The persisted outcome of a plan step. `PENDING` exists only as a
    transient in-memory value before a `SUBSTITUTED_EXECUTION` step is
    actually executed — a `ReplayStep` row is inserted once, already in
    its final status, never updated afterward (see
    docs/DECISIONS.md on why `replay_steps` has no interim-state
    mutation, unlike `replay_runs`)."""

    PENDING = "pending"
    REUSED = "reused"
    EXECUTED = "executed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PROVIDER_REQUIRED = "provider_required"


@dataclass(frozen=True)
class TrajectoryEventView:
    """The subset of a `TrajectoryEvent` the planner needs, decoupled
    from the ORM so `app/replay/planner.py` stays pure/dependency-free
    and unit-testable without a database."""

    id: uuid.UUID
    sequence_number: int
    event_type: EventType
    component_id: uuid.UUID | None
    component_version_id: uuid.UUID | None
    input: Any
    output: Any


@dataclass(frozen=True)
class ReplayPlanStep:
    """One deterministic step of a `ReplayPlan`. `execution_component_version_id`
    is the version to use for this step: the candidate for a substituted
    step, the historical version for a reused step, `None` for
    provider-required/skipped steps."""

    source_event_id: uuid.UUID
    sequence_number: int
    event_type: EventType
    kind: StepKind
    component_id: uuid.UUID | None
    execution_component_version_id: uuid.UUID | None
    historical_input: Any
    historical_output: Any
    justification: str | None = None


@dataclass(frozen=True)
class ReplayPlan:
    """An ordered, deterministic plan built from one trajectory's events
    plus a baseline/candidate substitution — never mutates the source
    trajectory, and building the same inputs twice always yields the
    same plan (Phase 7 §3/§5)."""

    steps: tuple[ReplayPlanStep, ...]

    def substituted_steps(self) -> tuple[ReplayPlanStep, ...]:
        return tuple(s for s in self.steps if s.kind == StepKind.SUBSTITUTED_EXECUTION)


@dataclass(frozen=True)
class ExecutionOutcome:
    """What a `ReplayExecutor` returns for one substituted step. `status`
    is `"executed"` (the candidate ran, output/error reflect what it
    returned) or `"failed"` (the candidate was invoked but failed) —
    never a silent fallback to historical output (Phase 7 §11)."""

    status: str
    output: Any = None
    error: Any = None
    duration_ms: int | None = None
