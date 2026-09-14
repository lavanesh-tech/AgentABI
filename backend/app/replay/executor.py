"""Replay executor contract (Phase 7 §8/§9) — a clean, provider-neutral
boundary future model/tool/MCP/API adapters plug into. Nothing here
calls an external service; `FakeReplayExecutor` is the only
implementation this phase ships, deterministic and in-memory, for
proving replay orchestration in tests.
"""

import uuid
from collections.abc import Sequence
from typing import Any, Protocol

from app.replay.models import ExecutionOutcome
from app.trajectory.models import EventType


class ReplayExecutor(Protocol):
    """A pluggable adapter capable of (re-)executing a substituted step.
    Future phases add a real `ToolExecutor`/`MCPExecutor`/`APIExecutor`
    (and, from Phase 8/9, a provider-backed model executor) implementing
    this same contract; the replay service never imports a concrete
    executor type directly."""

    def supports(self, event_type: EventType) -> bool: ...

    def execute(
        self, *, event_type: EventType, component_version_id: uuid.UUID | None, input: Any
    ) -> ExecutionOutcome: ...


class ExecutorRegistry:
    """Picks the first registered executor that supports a given event
    type. Empty by default — the production API wires no executors in
    Phase 7 (there is nothing real to execute yet), so any replay
    actually reaching a `SUBSTITUTED_EXECUTION` step deterministically
    raises `ReplayExecutorUnavailable` rather than pretending to run
    something."""

    def __init__(self, executors: Sequence[ReplayExecutor] = ()) -> None:
        self._executors: list[ReplayExecutor] = list(executors)

    def register(self, executor: ReplayExecutor) -> None:
        self._executors.append(executor)

    def find(self, event_type: EventType) -> ReplayExecutor | None:
        for executor in self._executors:
            if executor.supports(event_type):
                return executor
        return None


class FakeReplayExecutor:
    """Deterministic, in-memory, test-only executor (Phase 7 §9). Never
    wired into production paths. Returns predefined `ExecutionOutcome`s
    keyed by `(event_type, component_version_id)`, falling back to a
    single default outcome, and records every invocation's input for
    assertions."""

    def __init__(
        self,
        responses: dict[tuple[EventType, uuid.UUID | None], ExecutionOutcome] | None = None,
        default: ExecutionOutcome | None = None,
        supported_types: Sequence[EventType] | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._default = default or ExecutionOutcome(status="executed", output=None)
        self._supported = frozenset(
            supported_types or (EventType.TOOL_CALL, EventType.MCP_REQUEST, EventType.API_REQUEST)
        )
        self.invocations: list[dict[str, Any]] = []

    def supports(self, event_type: EventType) -> bool:
        return event_type in self._supported

    def execute(
        self, *, event_type: EventType, component_version_id: uuid.UUID | None, input: Any
    ) -> ExecutionOutcome:
        self.invocations.append(
            {
                "event_type": event_type,
                "component_version_id": component_version_id,
                "input": input,
            }
        )
        return self._responses.get((event_type, component_version_id), self._default)
