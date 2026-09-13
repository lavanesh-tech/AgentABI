"""Compatibility scan API — run a deterministic compatibility scan
between two versions of the same component, and retrieve past scans.

Thin by design: no comparison logic here (that's `app/compatibility/`),
no persistence details beyond calling the service. Domain exceptions are
translated to HTTP responses centrally in `app/api/v1/errors.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.compatibility.models import Classification, CompatibilityStatus, Severity
from app.core.database import get_db_session
from app.models.compatibility_scan import CompatibilityScan
from app.services.compatibility_service import CompatibilityService

router = APIRouter(prefix="/projects/{project_id}/compatibility", tags=["compatibility"])


class ScanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: uuid.UUID
    baseline_version: str = Field(min_length=1, max_length=50)
    candidate_version: str = Field(min_length=1, max_length=50)


class ScanChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_index: int
    change_type: str
    path: str
    classification: Classification
    severity: Severity
    message: str
    old_value: object | None
    new_value: object | None
    evidence: dict[str, object] | None


class ScanSummary(BaseModel):
    total_changes: int
    compatible_count: int
    potentially_breaking_count: int
    breaking_count: int
    severity_info_count: int
    severity_low_count: int
    severity_medium_count: int
    severity_high_count: int
    severity_critical_count: int


class ScanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    component_id: uuid.UUID
    baseline_version_id: uuid.UUID
    candidate_version_id: uuid.UUID
    status: CompatibilityStatus
    created_at: datetime
    summary: ScanSummary
    changes: list[ScanChangeResponse]

    @classmethod
    def from_scan(cls, scan: CompatibilityScan) -> "ScanResponse":
        return cls(
            id=scan.id,
            project_id=scan.project_id,
            component_id=scan.component_id,
            baseline_version_id=scan.baseline_version_id,
            candidate_version_id=scan.candidate_version_id,
            status=scan.status,
            created_at=scan.created_at,
            summary=ScanSummary(
                total_changes=scan.total_changes,
                compatible_count=scan.compatible_count,
                potentially_breaking_count=scan.potentially_breaking_count,
                breaking_count=scan.breaking_count,
                severity_info_count=scan.severity_info_count,
                severity_low_count=scan.severity_low_count,
                severity_medium_count=scan.severity_medium_count,
                severity_high_count=scan.severity_high_count,
                severity_critical_count=scan.severity_critical_count,
            ),
            changes=[ScanChangeResponse.model_validate(c) for c in scan.changes],
        )


class ScanListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    component_id: uuid.UUID
    baseline_version_id: uuid.UUID
    candidate_version_id: uuid.UUID
    status: CompatibilityStatus
    created_at: datetime
    summary: ScanSummary

    @classmethod
    def from_scan(cls, scan: CompatibilityScan) -> "ScanListItemResponse":
        return cls(
            id=scan.id,
            component_id=scan.component_id,
            baseline_version_id=scan.baseline_version_id,
            candidate_version_id=scan.candidate_version_id,
            status=scan.status,
            created_at=scan.created_at,
            summary=ScanSummary(
                total_changes=scan.total_changes,
                compatible_count=scan.compatible_count,
                potentially_breaking_count=scan.potentially_breaking_count,
                breaking_count=scan.breaking_count,
                severity_info_count=scan.severity_info_count,
                severity_low_count=scan.severity_low_count,
                severity_medium_count=scan.severity_medium_count,
                severity_high_count=scan.severity_high_count,
                severity_critical_count=scan.severity_critical_count,
            ),
        )


class ScanListResponse(BaseModel):
    items: list[ScanListItemResponse]
    total: int
    page: int
    page_size: int


def get_compatibility_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CompatibilityService:
    return CompatibilityService(session)


ServiceDep = Annotated[CompatibilityService, Depends(get_compatibility_service)]


@router.post("/scans", response_model=ScanResponse, status_code=status.HTTP_201_CREATED)
async def create_scan(
    project_id: uuid.UUID, payload: ScanCreateRequest, service: ServiceDep
) -> ScanResponse:
    scan = await service.run_scan(
        project_id, payload.component_id, payload.baseline_version, payload.candidate_version
    )
    return ScanResponse.from_scan(scan)


@router.get("/scans", response_model=ScanListResponse)
async def list_scans(
    project_id: uuid.UUID,
    service: ServiceDep,
    component_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ScanListResponse:
    result = await service.list_scans(
        project_id, component_id=component_id, page=page, page_size=page_size
    )
    return ScanListResponse(
        items=[ScanListItemResponse.from_scan(s) for s in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/scans/{scan_id}", response_model=ScanResponse)
async def get_scan(project_id: uuid.UUID, scan_id: uuid.UUID, service: ServiceDep) -> ScanResponse:
    scan = await service.get_scan(project_id, scan_id)
    return ScanResponse.from_scan(scan)


@router.get("/scans/{scan_id}/changes", response_model=list[ScanChangeResponse])
async def get_scan_changes(
    project_id: uuid.UUID, scan_id: uuid.UUID, service: ServiceDep
) -> list[ScanChangeResponse]:
    scan = await service.get_scan(project_id, scan_id)
    return [ScanChangeResponse.model_validate(c) for c in scan.changes]
