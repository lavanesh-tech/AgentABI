"""TrajectoryRecorderService — the single place trajectory-recording
business rules live. API routes call this service; they never touch
repositories or ORM models directly (Phase 6 §11).

Orchestration only: redaction (`app/trajectory/redaction.py`), size
enforcement (`app/trajectory/payload_limits.py`), shape validation
(`app/trajectory/validation.py`), transition rules
(`app/trajectory/transitions.py`), and hashing
(`app/trajectory/hashing.py`) are all pure, independently-testable
modules this service calls in a fixed order — never re-implemented here.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    ComponentNotFound,
    ComponentVersionNotFound,
    DuplicateTrajectoryEvent,
    InvalidTrajectoryEvent,
    InvalidTrajectoryTransition,
    ProjectNotFound,
    TrajectoryAlreadyExists,
    TrajectoryNotFound,
    TrajectoryTerminal,
)
from app.models.project import Project
from app.models.trajectory import Trajectory
from app.models.trajectory_event import TrajectoryEvent
from app.repositories.component_repository import ComponentRepository
from app.repositories.component_version_repository import ComponentVersionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.trajectory_repository import TrajectoryRepository
from app.services.component_registry import Page
from app.trajectory.hashing import compute_event_hash
from app.trajectory.models import EventType, TrajectoryStatus
from app.trajectory.payload_limits import enforce_payload_limit
from app.trajectory.redaction import sanitize
from app.trajectory.transitions import is_valid_transition
from app.trajectory.validation import validate_event_shape


class TrajectoryRecorderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._trajectories = TrajectoryRepository(session)
        self._components = ComponentRepository(session)
        self._versions = ComponentVersionRepository(session)
        self._projects = ProjectRepository(session)

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    async def _resolve_component_reference(
        self,
        project_id: uuid.UUID,
        component_id: uuid.UUID | None,
        component_version_id: uuid.UUID | None,
    ) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """Validates that a (component, component_version) reference is
        internally consistent and belongs to `project_id` (Phase 6 §6/§21
        — component-version references never cross project boundaries).
        Returns the resolved `(component_id, component_version_id)`.
        """

        if component_version_id is not None:
            version = await self._versions.get_by_id(component_version_id)
            if version is None:
                raise ComponentVersionNotFound(component_id, str(component_version_id))
            if component_id is not None and version.component_id != component_id:
                raise InvalidTrajectoryEvent(
                    f"component_version_id {component_version_id} does not belong to "
                    f"component_id {component_id}"
                )
            component = await self._components.get_by_id(project_id, version.component_id)
            if component is None:
                raise ComponentNotFound(version.component_id)
            return component.id, version.id

        if component_id is not None:
            component = await self._components.get_by_id(project_id, component_id)
            if component is None:
                raise ComponentNotFound(component_id)
            return component.id, None

        return None, None

    @staticmethod
    def _conflicts_with_existing(
        existing: Trajectory,
        *,
        workflow_component_id: uuid.UUID | None,
        workflow_version_id: uuid.UUID | None,
        environment: str | None,
    ) -> bool:
        """An `external_run_id` retry is idempotent (returns the existing
        trajectory) only when the newly-declared identifying fields agree
        with what's already stored — a genuinely different run reusing
        the same id by mistake is rejected instead (Phase 6 §13)."""

        if (
            workflow_component_id is not None
            and existing.workflow_component_id is not None
            and existing.workflow_component_id != workflow_component_id
        ):
            return True
        if (
            workflow_version_id is not None
            and existing.workflow_version_id is not None
            and existing.workflow_version_id != workflow_version_id
        ):
            return True
        return bool(
            environment is not None
            and existing.environment is not None
            and existing.environment != environment
        )

    async def start_trajectory(
        self,
        project_id: uuid.UUID,
        *,
        workflow_component_id: uuid.UUID | None = None,
        workflow_version_id: uuid.UUID | None = None,
        external_run_id: str | None = None,
        environment: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Trajectory:
        project = await self._require_project(project_id)
        workflow_component_id, workflow_version_id = await self._resolve_component_reference(
            project_id, workflow_component_id, workflow_version_id
        )

        if external_run_id is not None:
            existing = await self._trajectories.get_by_external_run_id(project_id, external_run_id)
            if existing is not None:
                if self._conflicts_with_existing(
                    existing,
                    workflow_component_id=workflow_component_id,
                    workflow_version_id=workflow_version_id,
                    environment=environment,
                ):
                    raise TrajectoryAlreadyExists(project_id, external_run_id)
                return existing

        trajectory = Trajectory(
            organization_id=project.organization_id,
            project_id=project_id,
            workflow_component_id=workflow_component_id,
            workflow_version_id=workflow_version_id,
            external_run_id=external_run_id,
            status=TrajectoryStatus.RUNNING,
            environment=environment,
            correlation_id=correlation_id,
            trace_id=trace_id,
            span_id=span_id,
            tags=tags,
            trajectory_metadata=metadata,
        )
        self._trajectories.add(trajectory)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Race-condition safety net, same pattern as
            # ComponentRegistryService.create_component (Phase 3): two
            # concurrent starts with the same external_run_id both pass
            # the pre-check above, then both try to insert.
            await self._session.rollback()
            if external_run_id is not None:
                existing = await self._trajectories.get_by_external_run_id(
                    project_id, external_run_id
                )
                if existing is not None:
                    if self._conflicts_with_existing(
                        existing,
                        workflow_component_id=workflow_component_id,
                        workflow_version_id=workflow_version_id,
                        environment=environment,
                    ):
                        raise TrajectoryAlreadyExists(project_id, external_run_id) from exc
                    return existing
            raise
        return trajectory

    async def get_trajectory(self, project_id: uuid.UUID, trajectory_id: uuid.UUID) -> Trajectory:
        trajectory = await self._trajectories.get_by_id(project_id, trajectory_id)
        if trajectory is None:
            raise TrajectoryNotFound(trajectory_id)
        return trajectory

    async def count_events(self, trajectory_id: uuid.UUID) -> int:
        """Explicit event count for one trajectory — see
        `TrajectoryRepository.count_events`'s docstring for why this is
        never derived from `Trajectory.events` at the API layer. Callers
        must already have established `trajectory_id` belongs to the
        caller's project (e.g. via a prior `get_trajectory`/
        `start_trajectory`/`_transition` call) — this method does no
        tenant check of its own, matching every other thin repository
        delegate in this service."""

        return await self._trajectories.count_events(trajectory_id)

    async def count_events_for_trajectories(
        self, trajectory_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        return await self._trajectories.count_events_for_trajectories(trajectory_ids)

    async def list_trajectories(
        self,
        project_id: uuid.UUID,
        *,
        status: TrajectoryStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[Trajectory]:
        await self._require_project(project_id)
        offset = (page - 1) * page_size
        items, total = await self._trajectories.list_by_project(
            project_id, status=status, offset=offset, limit=page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def append_event(
        self,
        project_id: uuid.UUID,
        trajectory_id: uuid.UUID,
        *,
        event_type: EventType,
        occurred_at: datetime | None = None,
        component_id: uuid.UUID | None = None,
        component_version_id: uuid.UUID | None = None,
        parent_event_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
        external_event_id: str | None = None,
        input: Any = None,  # noqa: A002 - matches the domain vocabulary (Phase 6 §2)
        output: Any = None,
        error: Any = None,
        metadata: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> TrajectoryEvent:
        trajectory = await self.get_trajectory(project_id, trajectory_id)

        # Redaction happens before anything else touches the payload —
        # validation, hashing, and storage all operate on the sanitized
        # shape, so a secret never reaches any of them (Phase 6 §9).
        sanitized_input = sanitize(input)
        sanitized_output = sanitize(output)
        sanitized_error = sanitize(error)
        sanitized_metadata = sanitize(metadata)

        validate_event_shape(
            event_type, input_payload=sanitized_input, error_payload=sanitized_error
        )

        resolved_component_id, resolved_version_id = await self._resolve_component_reference(
            project_id, component_id, component_version_id
        )

        if parent_event_id is not None and not any(
            e.id == parent_event_id for e in trajectory.events
        ):
            raise InvalidTrajectoryEvent(
                f"parent_event_id {parent_event_id} is not an event of trajectory {trajectory_id}"
            )

        input_stored, input_truncated, input_size = enforce_payload_limit(
            sanitized_input, field_name="input"
        )
        output_stored, output_truncated, output_size = enforce_payload_limit(
            sanitized_output, field_name="output"
        )
        error_stored, error_truncated, error_size = enforce_payload_limit(
            sanitized_error, field_name="error"
        )
        metadata_stored, metadata_truncated, metadata_size = enforce_payload_limit(
            sanitized_metadata, field_name="metadata"
        )
        truncated = input_truncated or output_truncated or error_truncated or metadata_truncated
        original_size = max(
            (s for s in (input_size, output_size, error_size, metadata_size) if s is not None),
            default=None,
        )

        if external_event_id is not None:
            existing_event = await self._trajectories.get_event_by_external_id(
                trajectory_id, external_event_id
            )
            if existing_event is not None:
                return self._reconcile_duplicate(
                    existing_event,
                    trajectory_id=trajectory_id,
                    external_event_id=external_event_id,
                    event_type=event_type,
                    component_version_id=resolved_version_id,
                    input_stored=input_stored,
                    output_stored=output_stored,
                    error_stored=error_stored,
                )

        sequence_number = await self._trajectories.allocate_sequence(trajectory_id)
        if sequence_number is None:
            await self._session.refresh(trajectory)
            raise TrajectoryTerminal(trajectory_id, trajectory.status)

        content_hash = compute_event_hash(
            trajectory_id=trajectory_id,
            sequence_number=sequence_number,
            event_type=event_type.value,
            component_version_id=resolved_version_id,
            input_payload=input_stored,
            output_payload=output_stored,
            error_payload=error_stored,
        )

        event_kwargs: dict[str, Any] = {
            "trajectory_id": trajectory_id,
            "sequence_number": sequence_number,
            "event_type": event_type,
            "component_id": resolved_component_id,
            "component_version_id": resolved_version_id,
            "parent_event_id": parent_event_id,
            "correlation_id": correlation_id,
            "external_event_id": external_event_id,
            "input": input_stored,
            "output": output_stored,
            "error": error_stored,
            "event_metadata": metadata_stored,
            "duration_ms": duration_ms,
            "payload_truncated": truncated,
            "payload_original_size_bytes": original_size,
            "content_hash": content_hash,
        }
        if occurred_at is not None:
            event_kwargs["occurred_at"] = occurred_at

        event = TrajectoryEvent(**event_kwargs)
        self._trajectories.add_event(event)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            if external_event_id is not None:
                existing_event = await self._trajectories.get_event_by_external_id(
                    trajectory_id, external_event_id
                )
                if existing_event is not None:
                    if existing_event.content_hash == content_hash:
                        return existing_event
                    raise DuplicateTrajectoryEvent(trajectory_id, external_event_id) from exc
            raise
        return event

    @staticmethod
    def _reconcile_duplicate(
        existing_event: TrajectoryEvent,
        *,
        trajectory_id: uuid.UUID,
        external_event_id: str,
        event_type: EventType,
        component_version_id: uuid.UUID | None,
        input_stored: Any,
        output_stored: Any,
        error_stored: Any,
    ) -> TrajectoryEvent:
        """Compares an incoming append against a previously-recorded
        event sharing the same `external_event_id`. An exact-duplicate
        retry (identical hash) is idempotent — the existing row is
        returned, no new event is created and no sequence number is
        consumed. Reusing the id for genuinely different event data is
        rejected (Phase 6 §14)."""

        candidate_hash = compute_event_hash(
            trajectory_id=trajectory_id,
            sequence_number=existing_event.sequence_number,
            event_type=event_type.value,
            component_version_id=component_version_id,
            input_payload=input_stored,
            output_payload=output_stored,
            error_payload=error_stored,
        )
        if existing_event.content_hash == candidate_hash:
            return existing_event
        raise DuplicateTrajectoryEvent(trajectory_id, external_event_id)

    async def list_events(
        self,
        project_id: uuid.UUID,
        trajectory_id: uuid.UUID,
        *,
        event_type: EventType | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Page[TrajectoryEvent]:
        await self.get_trajectory(project_id, trajectory_id)
        offset = (page - 1) * page_size
        items, total = await self._trajectories.list_events(
            trajectory_id, event_type=event_type, offset=offset, limit=page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def _transition(
        self,
        project_id: uuid.UUID,
        trajectory_id: uuid.UUID,
        target_status: TrajectoryStatus,
        error: str | None,
    ) -> Trajectory:
        trajectory = await self.get_trajectory(project_id, trajectory_id)
        if not is_valid_transition(trajectory.status, target_status):
            raise InvalidTrajectoryTransition(trajectory_id, trajectory.status, target_status)

        updated = await self._trajectories.transition_status(
            trajectory_id,
            from_status=trajectory.status,
            to_status=target_status,
            error=error,
        )
        if not updated:
            # A concurrent transition beat us to it between the read
            # above and this atomic conditional update.
            await self._session.refresh(trajectory)
            raise InvalidTrajectoryTransition(trajectory_id, trajectory.status, target_status)

        await self._session.refresh(trajectory)
        return trajectory

    async def complete_trajectory(
        self, project_id: uuid.UUID, trajectory_id: uuid.UUID
    ) -> Trajectory:
        return await self._transition(project_id, trajectory_id, TrajectoryStatus.COMPLETED, None)

    async def fail_trajectory(
        self, project_id: uuid.UUID, trajectory_id: uuid.UUID, *, error: str | None = None
    ) -> Trajectory:
        return await self._transition(project_id, trajectory_id, TrajectoryStatus.FAILED, error)

    # Deliberately no `update_event`/`delete_event`: once recorded, a
    # trajectory event is historical evidence — nothing in this service
    # can mutate one, and a database trigger (migration 0004) blocks it
    # even for a write that bypasses this service.
