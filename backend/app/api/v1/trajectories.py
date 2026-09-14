"""Trajectory recording API — start/record/complete/fail a trajectory and
retrieve it or its ordered events.

Thin by design: no recording logic here (that's
`app/services/trajectory_recorder.py`), no ORM objects crossing the API
boundary. Domain exceptions are translated to HTTP responses centrally
in `app/api/v1/errors.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_project_permission
from app.authz.permissions import Permission
from app.core.database import get_db_session
from app.models.trajectory import Trajectory
from app.models.trajectory_event import TrajectoryEvent
from app.services.trajectory_recorder import TrajectoryRecorderService
from app.trajectory.models import EventType, TrajectoryStatus

router = APIRouter(prefix="/projects/{project_id}/trajectories", tags=["trajectories"])

_READ = Depends(require_project_permission(Permission.TRAJECTORY_READ))
_WRITE = Depends(require_project_permission(Permission.TRAJECTORY_WRITE))


class TrajectoryStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_component_id: uuid.UUID | None = None
    workflow_version_id: uuid.UUID | None = None
    external_run_id: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=100)
    correlation_id: str | None = Field(default=None, max_length=255)
    trace_id: str | None = Field(default=None, max_length=255)
    span_id: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class TrajectoryFailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str | None = None


class EventAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    occurred_at: datetime | None = None
    component_id: uuid.UUID | None = None
    component_version_id: uuid.UUID | None = None
    parent_event_id: uuid.UUID | None = None
    correlation_id: str | None = Field(default=None, max_length=255)
    external_event_id: str | None = Field(default=None, max_length=255)
    input: Any = None
    output: Any = None
    error: Any = None
    metadata: dict[str, Any] | None = None
    duration_ms: int | None = None


class TrajectoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    workflow_component_id: uuid.UUID | None
    workflow_version_id: uuid.UUID | None
    external_run_id: str | None
    status: TrajectoryStatus
    environment: str | None
    correlation_id: str | None
    trace_id: str | None
    span_id: str | None
    tags: list[str] | None
    metadata: dict[str, Any] | None
    error: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: float | None
    event_count: int

    @classmethod
    def from_trajectory(cls, trajectory: Trajectory) -> "TrajectoryResponse":
        duration_seconds = None
        if trajectory.completed_at is not None:
            duration_seconds = (trajectory.completed_at - trajectory.started_at).total_seconds()
        return cls(
            id=trajectory.id,
            project_id=trajectory.project_id,
            organization_id=trajectory.organization_id,
            workflow_component_id=trajectory.workflow_component_id,
            workflow_version_id=trajectory.workflow_version_id,
            external_run_id=trajectory.external_run_id,
            status=trajectory.status,
            environment=trajectory.environment,
            correlation_id=trajectory.correlation_id,
            trace_id=trajectory.trace_id,
            span_id=trajectory.span_id,
            tags=trajectory.tags,
            metadata=trajectory.trajectory_metadata,
            error=trajectory.error,
            started_at=trajectory.started_at,
            completed_at=trajectory.completed_at,
            duration_seconds=duration_seconds,
            event_count=len(trajectory.events),
        )


class TrajectoryListResponse(BaseModel):
    items: list[TrajectoryResponse]
    total: int
    page: int
    page_size: int


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    trajectory_id: uuid.UUID
    sequence_number: int
    event_type: EventType
    occurred_at: datetime
    recorded_at: datetime
    component_id: uuid.UUID | None
    component_version_id: uuid.UUID | None
    parent_event_id: uuid.UUID | None
    correlation_id: str | None
    external_event_id: str | None
    input: Any | None
    output: Any | None
    error: Any | None
    metadata: dict[str, Any] | None
    duration_ms: int | None
    payload_truncated: bool
    payload_original_size_bytes: int | None
    content_hash: str

    @classmethod
    def from_event(cls, event: TrajectoryEvent) -> "EventResponse":
        return cls(
            id=event.id,
            trajectory_id=event.trajectory_id,
            sequence_number=event.sequence_number,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            recorded_at=event.recorded_at,
            component_id=event.component_id,
            component_version_id=event.component_version_id,
            parent_event_id=event.parent_event_id,
            correlation_id=event.correlation_id,
            external_event_id=event.external_event_id,
            input=event.input,
            output=event.output,
            error=event.error,
            metadata=event.event_metadata,
            duration_ms=event.duration_ms,
            payload_truncated=event.payload_truncated,
            payload_original_size_bytes=event.payload_original_size_bytes,
            content_hash=event.content_hash,
        )


class EventListResponse(BaseModel):
    items: list[EventResponse]
    total: int
    page: int
    page_size: int


def get_trajectory_recorder(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TrajectoryRecorderService:
    return TrajectoryRecorderService(session)


ServiceDep = Annotated[TrajectoryRecorderService, Depends(get_trajectory_recorder)]


@router.post(
    "",
    response_model=TrajectoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def start_trajectory(
    project_id: uuid.UUID, payload: TrajectoryStartRequest, service: ServiceDep
) -> TrajectoryResponse:
    trajectory = await service.start_trajectory(
        project_id,
        workflow_component_id=payload.workflow_component_id,
        workflow_version_id=payload.workflow_version_id,
        external_run_id=payload.external_run_id,
        environment=payload.environment,
        correlation_id=payload.correlation_id,
        trace_id=payload.trace_id,
        span_id=payload.span_id,
        tags=payload.tags,
        metadata=payload.metadata,
    )
    return TrajectoryResponse.from_trajectory(trajectory)


@router.get("", response_model=TrajectoryListResponse, dependencies=[_READ])
async def list_trajectories(
    project_id: uuid.UUID,
    service: ServiceDep,
    status_filter: Annotated[TrajectoryStatus | None, Query(alias="status")] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> TrajectoryListResponse:
    result = await service.list_trajectories(
        project_id, status=status_filter, page=page, page_size=page_size
    )
    return TrajectoryListResponse(
        items=[TrajectoryResponse.from_trajectory(t) for t in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/{trajectory_id}", response_model=TrajectoryResponse, dependencies=[_READ])
async def get_trajectory(
    project_id: uuid.UUID, trajectory_id: uuid.UUID, service: ServiceDep
) -> TrajectoryResponse:
    trajectory = await service.get_trajectory(project_id, trajectory_id)
    return TrajectoryResponse.from_trajectory(trajectory)


@router.post(
    "/{trajectory_id}/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def append_event(
    project_id: uuid.UUID,
    trajectory_id: uuid.UUID,
    payload: EventAppendRequest,
    service: ServiceDep,
) -> EventResponse:
    event = await service.append_event(
        project_id,
        trajectory_id,
        event_type=payload.event_type,
        occurred_at=payload.occurred_at,
        component_id=payload.component_id,
        component_version_id=payload.component_version_id,
        parent_event_id=payload.parent_event_id,
        correlation_id=payload.correlation_id,
        external_event_id=payload.external_event_id,
        input=payload.input,
        output=payload.output,
        error=payload.error,
        metadata=payload.metadata,
        duration_ms=payload.duration_ms,
    )
    return EventResponse.from_event(event)


@router.get("/{trajectory_id}/events", response_model=EventListResponse, dependencies=[_READ])
async def list_events(
    project_id: uuid.UUID,
    trajectory_id: uuid.UUID,
    service: ServiceDep,
    event_type: EventType | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> EventListResponse:
    result = await service.list_events(
        project_id, trajectory_id, event_type=event_type, page=page, page_size=page_size
    )
    return EventListResponse(
        items=[EventResponse.from_event(e) for e in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/{trajectory_id}/complete", response_model=TrajectoryResponse, dependencies=[_WRITE])
async def complete_trajectory(
    project_id: uuid.UUID, trajectory_id: uuid.UUID, service: ServiceDep
) -> TrajectoryResponse:
    trajectory = await service.complete_trajectory(project_id, trajectory_id)
    return TrajectoryResponse.from_trajectory(trajectory)


@router.post("/{trajectory_id}/fail", response_model=TrajectoryResponse, dependencies=[_WRITE])
async def fail_trajectory(
    project_id: uuid.UUID,
    trajectory_id: uuid.UUID,
    payload: TrajectoryFailRequest,
    service: ServiceDep,
) -> TrajectoryResponse:
    trajectory = await service.fail_trajectory(project_id, trajectory_id, error=payload.error)
    return TrajectoryResponse.from_trajectory(trajectory)
