"""ReplayService — the single place replay business rules live. API
routes call this service; they never touch repositories or ORM models
directly (mirrors `TrajectoryRecorderService`, Phase 6 §11).

Orchestration only: plan construction (`app/replay/planner.py`) and
transition rules (`app/replay/transitions.py`) are pure, independently-
testable modules this service calls in a fixed order — never
re-implemented here. No LLM, no provider call, no guessing: every
decision (what to substitute, what to reuse, whether execution
succeeded) comes from deterministic code (Phase 7's architectural
boundary).
"""

import time
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.exceptions import (
    ComponentNotFound,
    ComponentVersionNotFound,
    InvalidReplaySubstitution,
    InvalidReplayTransition,
    ProjectNotFound,
    ReplayAlreadyExists,
    ReplayExecutionFailed,
    ReplayExecutorUnavailable,
    ReplayNotFound,
    TrajectoryNotFound,
)
from app.models.project import Project
from app.models.replay_run import ReplayRun
from app.models.replay_step import ReplayStep
from app.observability import record_analysis_run, start_span
from app.replay.executor import ExecutorRegistry
from app.replay.models import ReplayPlan, ReplayStatus, StepKind, StepStatus, TrajectoryEventView
from app.replay.planner import build_replay_plan
from app.replay.transitions import is_valid_transition
from app.repositories.component_repository import ComponentRepository
from app.repositories.component_version_repository import ComponentVersionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.replay_repository import ReplayRepository
from app.repositories.trajectory_repository import TrajectoryRepository
from app.services.component_registry import Page
from app.trajectory.models import EventType, TrajectoryStatus

_KIND_TO_STATUS: dict[StepKind, StepStatus] = {
    StepKind.REUSED_EVIDENCE: StepStatus.REUSED,
    StepKind.PROVIDER_EXECUTION_REQUIRED: StepStatus.PROVIDER_REQUIRED,
    StepKind.SKIPPED: StepStatus.SKIPPED,
}


class ReplayService:
    def __init__(
        self, session: AsyncSession, *, executor_registry: ExecutorRegistry | None = None
    ) -> None:
        self._session = session
        self._replays = ReplayRepository(session)
        self._trajectories = TrajectoryRepository(session)
        self._components = ComponentRepository(session)
        self._versions = ComponentVersionRepository(session)
        self._projects = ProjectRepository(session)
        self._executors = executor_registry or ExecutorRegistry()

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    @staticmethod
    def _conflicts_with_existing(
        existing: ReplayRun,
        *,
        source_trajectory_id: uuid.UUID,
        baseline_component_version_id: uuid.UUID,
        candidate_component_version_id: uuid.UUID,
    ) -> bool:
        return (
            existing.source_trajectory_id != source_trajectory_id
            or existing.baseline_component_version_id != baseline_component_version_id
            or existing.candidate_component_version_id != candidate_component_version_id
        )

    async def create_replay(
        self,
        project_id: uuid.UUID,
        *,
        source_trajectory_id: uuid.UUID,
        baseline_component_version_id: uuid.UUID,
        candidate_component_version_id: uuid.UUID,
        idempotency_key: str | None = None,
        configuration: dict[str, Any] | None = None,
    ) -> ReplayRun:
        project = await self._require_project(project_id)

        if idempotency_key is not None:
            existing = await self._replays.get_by_idempotency_key(project_id, idempotency_key)
            if existing is not None:
                if self._conflicts_with_existing(
                    existing,
                    source_trajectory_id=source_trajectory_id,
                    baseline_component_version_id=baseline_component_version_id,
                    candidate_component_version_id=candidate_component_version_id,
                ):
                    raise ReplayAlreadyExists(project_id, idempotency_key)
                return existing

        trajectory = await self._trajectories.get_by_id(project_id, source_trajectory_id)
        if trajectory is None:
            raise TrajectoryNotFound(source_trajectory_id)
        if trajectory.status != TrajectoryStatus.COMPLETED:
            raise InvalidReplaySubstitution(
                f"source trajectory {source_trajectory_id} must be COMPLETED to replay "
                f"(status={trajectory.status!r})"
            )

        baseline = await self._versions.get_by_id(baseline_component_version_id)
        if baseline is None:
            raise ComponentVersionNotFound(None, str(baseline_component_version_id))
        candidate = await self._versions.get_by_id(candidate_component_version_id)
        if candidate is None:
            raise ComponentVersionNotFound(None, str(candidate_component_version_id))
        if baseline.component_id != candidate.component_id:
            raise InvalidReplaySubstitution(
                "candidate component version must belong to the same component as the baseline"
            )
        component = await self._components.get_by_id(project_id, baseline.component_id)
        if component is None:
            raise ComponentNotFound(baseline.component_id)

        views = [
            TrajectoryEventView(
                id=e.id,
                sequence_number=e.sequence_number,
                event_type=e.event_type,
                component_id=e.component_id,
                component_version_id=e.component_version_id,
                input=e.input,
                output=e.output,
            )
            for e in trajectory.events
        ]
        plan = build_replay_plan(
            views,
            baseline_component_id=component.id,
            baseline_version_id=baseline.id,
            candidate_version_id=candidate.id,
        )

        replay_run = ReplayRun(
            organization_id=project.organization_id,
            project_id=project_id,
            source_trajectory_id=source_trajectory_id,
            component_id=component.id,
            baseline_component_version_id=baseline.id,
            candidate_component_version_id=candidate.id,
            status=ReplayStatus.PENDING,
            idempotency_key=idempotency_key,
            configuration=configuration,
            plan=_serialize_plan(plan),
        )
        self._replays.add(replay_run)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            if idempotency_key is not None:
                existing = await self._replays.get_by_idempotency_key(project_id, idempotency_key)
                if existing is not None:
                    if self._conflicts_with_existing(
                        existing,
                        source_trajectory_id=source_trajectory_id,
                        baseline_component_version_id=baseline_component_version_id,
                        candidate_component_version_id=candidate_component_version_id,
                    ):
                        raise ReplayAlreadyExists(project_id, idempotency_key) from exc
                    return existing
            raise
        return replay_run

    async def get_replay(self, project_id: uuid.UUID, replay_id: uuid.UUID) -> ReplayRun:
        replay_run = await self._replays.get_by_id(project_id, replay_id)
        if replay_run is None:
            raise ReplayNotFound(replay_id)
        return replay_run

    async def count_steps(self, replay_run_id: uuid.UUID) -> int:
        """Explicit step count for one replay run — see
        `ReplayRepository.count_steps`'s docstring for why this is
        never derived from `ReplayRun.steps` at the API layer. Callers
        must already have established `replay_run_id` belongs to the
        caller's project (e.g. via a prior `get_replay`/`create_replay`/
        `execute_replay` call) — this method does no tenant check of
        its own, matching every other thin repository delegate in this
        service."""

        return await self._replays.count_steps(replay_run_id)

    async def count_steps_for_replays(
        self, replay_run_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        return await self._replays.count_steps_for_replays(replay_run_ids)

    async def list_replays(
        self,
        project_id: uuid.UUID,
        *,
        status: ReplayStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[ReplayRun]:
        await self._require_project(project_id)
        offset = (page - 1) * page_size
        items, total = await self._replays.list_by_project(
            project_id, status=status, offset=offset, limit=page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def list_steps(
        self, project_id: uuid.UUID, replay_id: uuid.UUID, *, page: int = 1, page_size: int = 50
    ) -> Page[ReplayStep]:
        await self.get_replay(project_id, replay_id)
        offset = (page - 1) * page_size
        items, total = await self._replays.list_steps(replay_id, offset=offset, limit=page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def execute_replay(self, project_id: uuid.UUID, replay_id: uuid.UUID) -> ReplayRun:
        """Phase 15 spec §14 domain span boundary."""

        start = time.monotonic()
        status = "success"
        with start_span(
            "agentabi.replay.execute",
            attributes={
                "agentabi.project_id": str(project_id),
                "agentabi.replay_id": str(replay_id),
            },
        ):
            try:
                return await self._execute_replay_impl(project_id, replay_id)
            except Exception:
                status = "failure"
                raise
            finally:
                record_analysis_run(
                    get_settings(),
                    pipeline="replay",
                    status=status,
                    duration_seconds=time.monotonic() - start,
                )

    async def _execute_replay_impl(self, project_id: uuid.UUID, replay_id: uuid.UUID) -> ReplayRun:
        replay_run = await self.get_replay(project_id, replay_id)

        if not is_valid_transition(replay_run.status, ReplayStatus.RUNNING):
            raise InvalidReplayTransition(replay_id, replay_run.status, ReplayStatus.RUNNING)
        applied = await self._replays.transition_status(
            replay_id,
            from_status=ReplayStatus.PENDING,
            to_status=ReplayStatus.RUNNING,
            started_at_now=True,
        )
        if not applied:
            await self._session.refresh(replay_run)
            raise InvalidReplayTransition(replay_id, replay_run.status, ReplayStatus.RUNNING)

        failure_reason: str | None = None
        for step in sorted(replay_run.plan, key=lambda s: s["sequence_number"]):
            kind = StepKind(step["kind"])
            if kind != StepKind.SUBSTITUTED_EXECUTION:
                self._replays.add_step(_finalized_step(replay_id, step, _KIND_TO_STATUS[kind]))
                continue

            event_type = EventType(step["event_type"])
            executor = self._executors.find(event_type)
            if executor is None:
                await self._session.flush()
                await self._replays.transition_status(
                    replay_id,
                    from_status=ReplayStatus.RUNNING,
                    to_status=ReplayStatus.FAILED,
                    error=f"no executor available for event_type={event_type!r}",
                    completed_at_now=True,
                )
                raise ReplayExecutorUnavailable(replay_id, event_type)

            try:
                outcome = executor.execute(
                    event_type=event_type,
                    component_version_id=_as_uuid(step["execution_component_version_id"]),
                    input=step["historical_input"],
                )
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any executor
                # failure, not just a domain one, must not crash the replay
                # in an inconsistent state (Phase 7 §11).
                await self._session.flush()
                await self._replays.transition_status(
                    replay_id,
                    from_status=ReplayStatus.RUNNING,
                    to_status=ReplayStatus.FAILED,
                    error=str(exc),
                    completed_at_now=True,
                )
                raise ReplayExecutionFailed(replay_id, str(exc)) from exc

            status = StepStatus.EXECUTED if outcome.status == "executed" else StepStatus.FAILED
            self._replays.add_step(
                ReplayStep(
                    replay_run_id=replay_id,
                    sequence_number=step["sequence_number"],
                    source_event_id=_as_uuid(step["source_event_id"]),
                    kind=kind,
                    status=status,
                    component_id=_as_uuid(step["component_id"]),
                    component_version_id=_as_uuid(step["execution_component_version_id"]),
                    input=step["historical_input"],
                    output=outcome.output,
                    error=outcome.error,
                    justification=step["justification"],
                    duration_ms=outcome.duration_ms,
                )
            )
            if status == StepStatus.FAILED:
                # Never fall back to historical output after a required
                # candidate execution fails (Phase 7 §11) — the failure
                # itself is the recorded evidence; stop here.
                failure_reason = (
                    f"substituted execution failed at sequence {step['sequence_number']}"
                )
                break

        await self._session.flush()
        if failure_reason is not None:
            await self._replays.transition_status(
                replay_id,
                from_status=ReplayStatus.RUNNING,
                to_status=ReplayStatus.FAILED,
                error=failure_reason,
                completed_at_now=True,
            )
        else:
            await self._replays.transition_status(
                replay_id,
                from_status=ReplayStatus.RUNNING,
                to_status=ReplayStatus.COMPLETED,
                completed_at_now=True,
            )
        await self._session.refresh(replay_run)
        return replay_run


def _serialize_plan(plan: ReplayPlan) -> list[dict[str, Any]]:
    return [
        {
            "source_event_id": str(step.source_event_id),
            "sequence_number": step.sequence_number,
            "event_type": step.event_type.value,
            "kind": step.kind.value,
            "component_id": str(step.component_id) if step.component_id else None,
            "execution_component_version_id": (
                str(step.execution_component_version_id)
                if step.execution_component_version_id
                else None
            ),
            "historical_input": step.historical_input,
            "historical_output": step.historical_output,
            "justification": step.justification,
        }
        for step in plan.steps
    ]


def _finalized_step(replay_id: uuid.UUID, step: dict[str, Any], status: StepStatus) -> ReplayStep:
    return ReplayStep(
        replay_run_id=replay_id,
        sequence_number=step["sequence_number"],
        source_event_id=_as_uuid(step["source_event_id"]),
        kind=StepKind(step["kind"]),
        status=status,
        component_id=_as_uuid(step["component_id"]),
        component_version_id=_as_uuid(step["execution_component_version_id"]),
        input=step["historical_input"],
        output=step["historical_output"] if status == StepStatus.REUSED else None,
        error=None,
        justification=step["justification"],
        duration_ms=None,
    )


def _as_uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value is not None else None
