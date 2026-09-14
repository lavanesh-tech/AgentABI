"""Differential analysis API — run and retrieve deterministic
comparisons between two completed replays of the same project (Phase
10). Thin by design: no comparison logic here (`app/differential/`),
no persistence details beyond calling the service.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_project_permission
from app.api.deps.rate_limit import rate_limit_by_user
from app.authz.permissions import Permission
from app.core.config import get_settings
from app.core.database import get_db_session
from app.models.differential_report import DifferentialReportRecord
from app.services.differential_service import DifferentialService

router = APIRouter(prefix="/projects/{project_id}/differential", tags=["differential"])

_READ = Depends(require_project_permission(Permission.DIFFERENTIAL_READ))
_EXECUTE = Depends(require_project_permission(Permission.DIFFERENTIAL_EXECUTE))

_settings = get_settings()
# Reuses Phase D's scan/replay high-cost bucket (spec §24) rather than a
# new limiter — differential analysis is the same cost class as running
# a scan or a replay.
_RATE_DIFFERENTIAL = Depends(
    rate_limit_by_user(
        "differential",
        _settings.rate_limit_scan_replay_requests,
        _settings.rate_limit_scan_replay_window_seconds,
    )
)


class DifferentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_replay_id: uuid.UUID
    candidate_replay_id: uuid.UUID
    compatibility_scan_id: uuid.UUID | None = Field(default=None)


class DifferentialChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_index: int
    alignment_method: str
    difference_types: list[str]
    sequence_number: int | None
    baseline_step_id: uuid.UUID | None
    candidate_step_id: uuid.UUID | None
    baseline_status: str | None
    candidate_status: str | None
    output_differences: list[dict]
    error_difference: dict | None
    latency_delta_ms: int | None
    latency_percent_delta: float | None


class DifferentialSummaryResponse(BaseModel):
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


class DifferentialReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    baseline_replay_id: uuid.UUID
    candidate_replay_id: uuid.UUID
    compatibility_scan_id: uuid.UUID | None
    analyzer_version: str
    content_hash: str
    created_at: datetime
    summary: DifferentialSummaryResponse
    changes: list[DifferentialChangeResponse]

    @classmethod
    def from_record(cls, record: DifferentialReportRecord) -> "DifferentialReportResponse":
        return cls(
            id=record.id,
            project_id=record.project_id,
            baseline_replay_id=record.baseline_replay_id,
            candidate_replay_id=record.candidate_replay_id,
            compatibility_scan_id=record.compatibility_scan_id,
            analyzer_version=record.analyzer_version,
            content_hash=record.content_hash,
            created_at=record.created_at,
            summary=DifferentialSummaryResponse(
                total_baseline_steps=record.total_baseline_steps,
                total_candidate_steps=record.total_candidate_steps,
                matched_steps=record.matched_steps,
                added_steps=record.added_steps,
                removed_steps=record.removed_steps,
                changed_steps=record.changed_steps,
                new_failures=record.new_failures,
                resolved_failures=record.resolved_failures,
                changed_outputs=record.changed_outputs,
                schema_changes=record.schema_changes,
            ),
            changes=[DifferentialChangeResponse.model_validate(c) for c in record.changes],
        )


class DifferentialListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    baseline_replay_id: uuid.UUID
    candidate_replay_id: uuid.UUID
    analyzer_version: str
    created_at: datetime
    summary: DifferentialSummaryResponse

    @classmethod
    def from_record(cls, record: DifferentialReportRecord) -> "DifferentialListItemResponse":
        return cls(
            id=record.id,
            baseline_replay_id=record.baseline_replay_id,
            candidate_replay_id=record.candidate_replay_id,
            analyzer_version=record.analyzer_version,
            created_at=record.created_at,
            summary=DifferentialSummaryResponse(
                total_baseline_steps=record.total_baseline_steps,
                total_candidate_steps=record.total_candidate_steps,
                matched_steps=record.matched_steps,
                added_steps=record.added_steps,
                removed_steps=record.removed_steps,
                changed_steps=record.changed_steps,
                new_failures=record.new_failures,
                resolved_failures=record.resolved_failures,
                changed_outputs=record.changed_outputs,
                schema_changes=record.schema_changes,
            ),
        )


class DifferentialListResponse(BaseModel):
    items: list[DifferentialListItemResponse]
    total: int
    page: int
    page_size: int


def get_differential_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DifferentialService:
    return DifferentialService(session)


ServiceDep = Annotated[DifferentialService, Depends(get_differential_service)]


@router.post(
    "/reports",
    response_model=DifferentialReportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_EXECUTE, _RATE_DIFFERENTIAL],
    summary="Run a deterministic differential analysis",
    description="Requires ADMIN or OWNER. Compares two COMPLETED replays "
    "in this project step-by-step (never an LLM). Retrying the same "
    "baseline/candidate pair at the current analyzer version returns the "
    "existing report rather than creating a duplicate.",
)
async def create_differential_report(
    project_id: uuid.UUID, payload: DifferentialCreateRequest, service: ServiceDep
) -> DifferentialReportResponse:
    record = await service.run_analysis(
        project_id,
        baseline_replay_id=payload.baseline_replay_id,
        candidate_replay_id=payload.candidate_replay_id,
        compatibility_scan_id=payload.compatibility_scan_id,
    )
    return DifferentialReportResponse.from_record(record)


@router.get(
    "/reports/{report_id}",
    response_model=DifferentialReportResponse,
    dependencies=[_READ],
)
async def get_differential_report(
    project_id: uuid.UUID, report_id: uuid.UUID, service: ServiceDep
) -> DifferentialReportResponse:
    record = await service.get_report(project_id, report_id)
    return DifferentialReportResponse.from_record(record)


@router.get("/reports", response_model=DifferentialListResponse, dependencies=[_READ])
async def list_differential_reports(
    project_id: uuid.UUID,
    service: ServiceDep,
    page: int = 1,
    page_size: int = 20,
) -> DifferentialListResponse:
    result = await service.list_reports(project_id, page=page, page_size=page_size)
    return DifferentialListResponse(
        items=[DifferentialListItemResponse.from_record(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
