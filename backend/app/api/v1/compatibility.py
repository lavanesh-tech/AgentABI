"""Compatibility scan API — run a deterministic compatibility scan
between two versions of the same component, and retrieve past scans.

Thin by design: no comparison logic here (that's `app/compatibility/`),
no persistence details beyond calling the service. Domain exceptions are
translated to HTTP responses centrally in `app/api/v1/errors.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_project_permission
from app.api.deps.llm import get_llm_provider
from app.api.deps.rate_limit import rate_limit_by_user
from app.authz.permissions import Permission
from app.compatibility.models import Classification, CompatibilityStatus, Severity
from app.core.config import get_settings
from app.core.database import get_db_session
from app.llm.provider import LLMProvider
from app.models.compatibility_scan import CompatibilityScan
from app.services.compatibility_service import CompatibilityService
from app.services.explanation_service import ExplanationService

router = APIRouter(prefix="/projects/{project_id}/compatibility", tags=["compatibility"])

_READ = Depends(require_project_permission(Permission.SCAN_READ))
_EXECUTE = Depends(require_project_permission(Permission.SCAN_EXECUTE))

_settings = get_settings()
_RATE_SCAN = Depends(
    rate_limit_by_user(
        "scan",
        _settings.rate_limit_scan_replay_requests,
        _settings.rate_limit_scan_replay_window_seconds,
    )
)


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


class EvidenceReferenceResponse(BaseModel):
    reference_id: str
    note: str = ""


class ExplanationResponseModel(BaseModel):
    """API shape for `app.llm.models.ExplanationResponse` — deliberately
    has no risk/decision field (spec §10). See
    `docs/ARCHITECTURE.md`'s Security/LLM boundary section."""

    summary: str
    key_findings: list[str]
    likely_impact: list[str]
    remediation_steps: list[str]
    evidence_references: list[EvidenceReferenceResponse]
    limitations: list[str]
    provider: str
    model: str


def get_compatibility_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CompatibilityService:
    return CompatibilityService(session)


ServiceDep = Annotated[CompatibilityService, Depends(get_compatibility_service)]


def get_explanation_service(
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ExplanationService:
    return ExplanationService(provider)


ExplanationServiceDep = Annotated[ExplanationService, Depends(get_explanation_service)]


@router.post(
    "/scans",
    response_model=ScanResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_EXECUTE, _RATE_SCAN],
)
async def create_scan(
    project_id: uuid.UUID, payload: ScanCreateRequest, service: ServiceDep
) -> ScanResponse:
    scan = await service.run_scan(
        project_id, payload.component_id, payload.baseline_version, payload.candidate_version
    )
    return ScanResponse.from_scan(scan)


@router.get("/scans", response_model=ScanListResponse, dependencies=[_READ])
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


@router.get("/scans/{scan_id}", response_model=ScanResponse, dependencies=[_READ])
async def get_scan(project_id: uuid.UUID, scan_id: uuid.UUID, service: ServiceDep) -> ScanResponse:
    scan = await service.get_scan(project_id, scan_id)
    return ScanResponse.from_scan(scan)


@router.get(
    "/scans/{scan_id}/changes", response_model=list[ScanChangeResponse], dependencies=[_READ]
)
async def get_scan_changes(
    project_id: uuid.UUID, scan_id: uuid.UUID, service: ServiceDep
) -> list[ScanChangeResponse]:
    scan = await service.get_scan(project_id, scan_id)
    return [ScanChangeResponse.model_validate(c) for c in scan.changes]


@router.post(
    "/scans/{scan_id}/explain",
    response_model=ExplanationResponseModel,
    dependencies=[_EXECUTE, _RATE_SCAN],
    summary="Explain a compatibility scan's changes in natural language",
    description="Requires the same permission and rate-limit bucket as "
    "triggering a scan (this calls OpenAI, which costs money). The "
    "explanation is generated only from this scan's already-computed, "
    "deterministic changes — the LLM never recalculates compatibility, "
    "and its response cannot contain a risk score or a pass/warn/block "
    "decision; those remain deterministic. Returns 503 if the OpenAI provider "
    "is not configured, 502/504 for upstream provider failures.",
)
async def explain_scan(
    project_id: uuid.UUID,
    scan_id: uuid.UUID,
    service: ServiceDep,
    explanation_service: ExplanationServiceDep,
) -> ExplanationResponseModel:
    scan = await service.get_scan(project_id, scan_id)
    result = await explanation_service.explain_compatibility_changes(
        subject=f"compatibility scan {scan_id} of component {scan.component_id}",
        baseline_label=str(scan.baseline_version_id),
        candidate_label=str(scan.candidate_version_id),
        changes=cast(Any, list(scan.changes)),
    )
    return ExplanationResponseModel(
        summary=result.summary,
        key_findings=list(result.key_findings),
        likely_impact=list(result.likely_impact),
        remediation_steps=list(result.remediation_steps),
        evidence_references=[
            EvidenceReferenceResponse(reference_id=r.reference_id, note=r.note)
            for r in result.evidence_references
        ],
        limitations=list(result.limitations),
        provider=result.provider,
        model=result.model,
    )
