"""Pure data shapes for the deterministic Differential Analyzer (Phase
10). No SQLAlchemy, no Pydantic, no OpenAI/LLM import — same dependency-
free choice as `app/compatibility/models.py` (Phase 5) and
`app/replay/models.py` (Phase 7): the entire comparison engine can be
imported and unit-tested without a database or provider installed.

Nothing here computes a risk score or deployment decision — that's
Phase 11's job. This module only records *what differs*, deterministically.
"""

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any


class DifferenceType(enum.StrEnum):
    """Centralized taxonomy (spec §6). Only categories this analyzer can
    actually detect from real replay-step data — no speculative
    categories."""

    STEP_ADDED = "STEP_ADDED"
    STEP_REMOVED = "STEP_REMOVED"
    STEP_STATUS_CHANGED = "STEP_STATUS_CHANGED"
    TOOL_CHANGED = "TOOL_CHANGED"
    INPUT_CHANGED = "INPUT_CHANGED"
    OUTPUT_CHANGED = "OUTPUT_CHANGED"
    ERROR_INTRODUCED = "ERROR_INTRODUCED"
    ERROR_RESOLVED = "ERROR_RESOLVED"
    ERROR_CHANGED = "ERROR_CHANGED"
    PROVIDER_INVOCATION_CHANGED = "PROVIDER_INVOCATION_CHANGED"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    VALUE_CHANGED = "VALUE_CHANGED"
    LATENCY_CHANGED = "LATENCY_CHANGED"


class AlignmentMethod(enum.StrEnum):
    """Which rule in the fallback hierarchy (spec §7) matched a pair of
    steps — recorded on every `StepDifference` for auditability, never
    silently discarded."""

    SOURCE_EVENT_ID = "source_event_id"
    SEQUENCE_NUMBER = "sequence_number"
    COMPONENT_IDENTITY = "component_identity"
    UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class ReplayStepView:
    """The subset of a `ReplayStep` the analyzer needs, decoupled from
    the ORM — mirrors `app.replay.models.TrajectoryEventView`'s reason
    for existing (Phase 7)."""

    id: uuid.UUID
    sequence_number: int
    source_event_id: uuid.UUID
    kind: str
    status: str
    component_id: uuid.UUID | None
    component_version_id: uuid.UUID | None
    input: Any
    output: Any
    error: Any
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class FieldDifference:
    """One leaf/field-level difference found while recursively comparing
    a baseline and candidate output (spec §10/§11)."""

    difference_type: DifferenceType
    path: str
    old_value: Any = None
    new_value: Any = None
    redacted: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ErrorDifference:
    """Safe, sanitized comparison of a step's error state (spec §13) —
    never a raw stack trace or provider secret, only category/code and
    presence/absence."""

    difference_type: DifferenceType
    baseline_present: bool
    candidate_present: bool
    baseline_category: str | None = None
    candidate_category: str | None = None


@dataclass(frozen=True, slots=True)
class LatencyDifference:
    """Only ever constructed when both sides have a real measured
    `duration_ms` (spec §14) — never fabricated."""

    baseline_duration_ms: int
    candidate_duration_ms: int
    delta_ms: int
    percent_delta: float | None
    """None when `baseline_duration_ms == 0` (percentage is undefined)."""


@dataclass(frozen=True, slots=True)
class StepDifference:
    """Everything different about one aligned (or unaligned) step pair."""

    alignment_method: AlignmentMethod
    difference_types: tuple[DifferenceType, ...]
    sequence_number: int | None
    baseline: ReplayStepView | None
    candidate: ReplayStepView | None
    output_differences: tuple[FieldDifference, ...] = ()
    error_difference: ErrorDifference | None = None
    latency_difference: LatencyDifference | None = None


@dataclass(frozen=True, slots=True)
class DifferentialSummary:
    """Deterministic aggregate metrics (spec §15) — no risk score."""

    total_baseline_steps: int
    total_candidate_steps: int
    matched_steps: int
    added_steps: int
    removed_steps: int
    changed_steps: int
    new_failures: int
    resolved_failures: int
    changed_outputs: int
    schema_changes: int


@dataclass(frozen=True, slots=True)
class DifferentialReport:
    """The complete, deterministic output of comparing one baseline
    replay's steps against one candidate replay's steps. Pure
    computation — contains no database identifiers of its own;
    `app/services/differential_service.py` is what persists one."""

    analyzer_version: str
    step_differences: tuple[StepDifference, ...]
    summary: DifferentialSummary

    @property
    def total_differences(self) -> int:
        return sum(len(sd.difference_types) for sd in self.step_differences)
