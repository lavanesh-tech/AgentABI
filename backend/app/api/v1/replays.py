"""Replay API — create a deterministic replay plan, execute it, and
retrieve the run or its ordered step evidence.

Thin by design: no orchestration logic here (that's
`app/services/replay_service.py`), no ORM objects crossing the API
boundary. Mirrors `app/api/v1/trajectories.py`.
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
from app.models.replay_run import ReplayRun
from app.models.replay_step import ReplayStep
from app.replay.models import ReplayStatus, StepKind, StepStatus
from app.services.replay_service import ReplayService

router = APIRouter(prefix="/projects/{project_id}/replays", tags=["replays"])

_READ = Depends(require_project_permission(Permission.REPLAY_READ))
_EXECUTE = Depends(require_project_permission(Permission.REPLAY_EXECUTE))


class ReplayCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_trajectory_id: uuid.UUID
    baseline_component_version_id: uuid.UUID
    candidate_component_version_id: uuid.UUID
    idempotency_key: str | None = Field(default=None, max_length=255)
    configuration: dict[str, Any] | None = None


class ReplayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    source_trajectory_id: uuid.UUID
    component_id: uuid.UUID
    baseline_component_version_id: uuid.UUID
    candidate_component_version_id: uuid.UUID
    status: ReplayStatus
    idempotency_key: str | None
    configuration: dict[str, Any] | None
    plan: list[dict[str, Any]]
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    step_count: int

    @classmethod
    def from_replay(cls, replay_run: ReplayRun) -> "ReplayResponse":
        return cls(
            id=replay_run.id,
            project_id=replay_run.project_id,
            organization_id=replay_run.organization_id,
            source_trajectory_id=replay_run.source_trajectory_id,
            component_id=replay_run.component_id,
            baseline_component_version_id=replay_run.baseline_component_version_id,
            candidate_component_version_id=replay_run.candidate_component_version_id,
            status=replay_run.status,
            idempotency_key=replay_run.idempotency_key,
            configuration=replay_run.configuration,
            plan=replay_run.plan,
            error=replay_run.error,
            started_at=replay_run.started_at,
            completed_at=replay_run.completed_at,
            step_count=len(replay_run.steps),
        )


class ReplayListResponse(BaseModel):
    items: list[ReplayResponse]
    total: int
    page: int
    page_size: int


class ReplayStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    replay_run_id: uuid.UUID
    sequence_number: int
    source_event_id: uuid.UUID
    kind: StepKind
    status: StepStatus
    component_id: uuid.UUID | None
    component_version_id: uuid.UUID | None
    input: Any | None
    output: Any | None
    error: Any | None
    justification: str | None
    duration_ms: int | None

    @classmethod
    def from_step(cls, step: ReplayStep) -> "ReplayStepResponse":
        return cls(
            id=step.id,
            replay_run_id=step.replay_run_id,
            sequence_number=step.sequence_number,
            source_event_id=step.source_event_id,
            kind=step.kind,
            status=step.status,
            component_id=step.component_id,
            component_version_id=step.component_version_id,
            input=step.input,
            output=step.output,
            error=step.error,
            justification=step.justification,
            duration_ms=step.duration_ms,
        )


class ReplayStepListResponse(BaseModel):
    items: list[ReplayStepResponse]
    total: int
    page: int
    page_size: int


def get_replay_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReplayService:
    return ReplayService(session)


ServiceDep = Annotated[ReplayService, Depends(get_replay_service)]


@router.post(
    "",
    response_model=ReplayResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_EXECUTE],
)
async def create_replay(
    project_id: uuid.UUID, payload: ReplayCreateRequest, service: ServiceDep
) -> ReplayResponse:
    replay_run = await service.create_replay(
        project_id,
        source_trajectory_id=payload.source_trajectory_id,
        baseline_component_version_id=payload.baseline_component_version_id,
        candidate_component_version_id=payload.candidate_component_version_id,
        idempotency_key=payload.idempotency_key,
        configuration=payload.configuration,
    )
    return ReplayResponse.from_replay(replay_run)


@router.get("", response_model=ReplayListResponse, dependencies=[_READ])
async def list_replays(
    project_id: uuid.UUID,
    service: ServiceDep,
    status_filter: Annotated[ReplayStatus | None, Query(alias="status")] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ReplayListResponse:
    result = await service.list_replays(
        project_id, status=status_filter, page=page, page_size=page_size
    )
    return ReplayListResponse(
        items=[ReplayResponse.from_replay(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/{replay_id}", response_model=ReplayResponse, dependencies=[_READ])
async def get_replay(
    project_id: uuid.UUID, replay_id: uuid.UUID, service: ServiceDep
) -> ReplayResponse:
    replay_run = await service.get_replay(project_id, replay_id)
    return ReplayResponse.from_replay(replay_run)


@router.post("/{replay_id}/execute", response_model=ReplayResponse, dependencies=[_EXECUTE])
async def execute_replay(
    project_id: uuid.UUID, replay_id: uuid.UUID, service: ServiceDep
) -> ReplayResponse:
    replay_run = await service.execute_replay(project_id, replay_id)
    return ReplayResponse.from_replay(replay_run)


@router.get("/{replay_id}/steps", response_model=ReplayStepListResponse, dependencies=[_READ])
async def list_steps(
    project_id: uuid.UUID,
    replay_id: uuid.UUID,
    service: ServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ReplayStepListResponse:
    result = await service.list_steps(project_id, replay_id, page=page, page_size=page_size)
    return ReplayStepListResponse(
        items=[ReplayStepResponse.from_step(s) for s in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
