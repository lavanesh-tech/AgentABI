"""Deterministic risk assessment API — run and retrieve risk decisions
over a compatibility scan and/or a differential report (Phase 11). Thin
by design: no scoring logic here (`app/risk/`), no persistence details
beyond calling the service. Designed as Phase 12's GitHub-check input
contract (spec §28): `decision`/`score`/`hard_block` are exactly the
fields a PR status check needs.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_project_permission
from app.api.deps.rate_limit import rate_limit_by_user
from app.authz.permissions import Permission
from app.core.config import get_settings
from app.core.database import get_db_session
from app.graph.client import get_driver
from app.graph.repository import Neo4jGraphRepository
from app.models.risk_assessment import RiskAssessmentRecord
from app.services.blast_radius import BlastRadiusService
from app.services.risk_service import RiskService

router = APIRouter(prefix="/projects/{project_id}/risk", tags=["risk"])

_READ = Depends(require_project_permission(Permission.RISK_READ))
_EXECUTE = Depends(require_project_permission(Permission.RISK_EXECUTE))

_settings = get_settings()
# Reuses Phase D's scan/replay high-cost bucket (spec §28) rather than a
# new limiter — running a risk assessment is the same cost class as
# running a scan, a replay, or a differential analysis.
_RATE_RISK = Depends(
    rate_limit_by_user(
        "risk",
        _settings.rate_limit_scan_replay_requests,
        _settings.rate_limit_scan_replay_window_seconds,
    )
)


class RiskAssessmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compatibility_scan_id: uuid.UUID | None = Field(default=None)
    differential_report_id: uuid.UUID | None = Field(default=None)

    @model_validator(mode="after")
    def _at_least_one_input(self) -> "RiskAssessmentCreateRequest":
        # Belt-and-suspenders: `RiskService.run_assessment` also raises
        # `RiskAssessmentInputRequired` for this — validating here just
        # gives a Pydantic-shaped 422 instead of a 400 for the common
        # case of an obviously empty request body.
        if self.compatibility_scan_id is None and self.differential_report_id is None:
            raise ValueError(
                "At least one of compatibility_scan_id or differential_report_id is required"
            )
        return self


class RiskRuleResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_index: int
    rule_id: str
    category: str
    description: str
    score_delta: int
    evidence_refs: list[str]
    hard_block: bool


class RiskAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    compatibility_scan_id: uuid.UUID | None
    differential_report_id: uuid.UUID | None
    risk_engine_version: str
    decision: str
    score: int
    hard_block: bool
    content_hash: str
    created_at: datetime
    rule_results: list[RiskRuleResultResponse]

    @classmethod
    def from_record(cls, record: RiskAssessmentRecord) -> "RiskAssessmentResponse":
        return cls(
            id=record.id,
            project_id=record.project_id,
            compatibility_scan_id=record.compatibility_scan_id,
            differential_report_id=record.differential_report_id,
            risk_engine_version=record.risk_engine_version,
            decision=record.decision,
            score=record.score,
            hard_block=record.hard_block,
            content_hash=record.content_hash,
            created_at=record.created_at,
            rule_results=[RiskRuleResultResponse.model_validate(r) for r in record.rule_results],
        )


class RiskAssessmentListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    compatibility_scan_id: uuid.UUID | None
    differential_report_id: uuid.UUID | None
    decision: str
    score: int
    hard_block: bool
    created_at: datetime

    @classmethod
    def from_record(cls, record: RiskAssessmentRecord) -> "RiskAssessmentListItemResponse":
        return cls(
            id=record.id,
            compatibility_scan_id=record.compatibility_scan_id,
            differential_report_id=record.differential_report_id,
            decision=record.decision,
            score=record.score,
            hard_block=record.hard_block,
            created_at=record.created_at,
        )


class RiskAssessmentListResponse(BaseModel):
    items: list[RiskAssessmentListItemResponse]
    total: int
    page: int
    page_size: int


def get_risk_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RiskService:
    # Blast-radius evidence is best-effort (spec §14): if Neo4j is
    # unreachable, `RiskService._compute_blast_radius` catches
    # `GraphUnavailable` per-call — the service is still constructed
    # eagerly here, same factory pattern as `app/api/v1/graph.py`.
    blast_radius = BlastRadiusService(Neo4jGraphRepository(get_driver()))
    return RiskService(session, blast_radius=blast_radius)


ServiceDep = Annotated[RiskService, Depends(get_risk_service)]


@router.post(
    "/assessments",
    response_model=RiskAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_EXECUTE, _RATE_RISK],
    summary="Run a deterministic risk assessment",
    description="Requires ADMIN or OWNER. Evaluates a compatibility "
    "scan and/or a differential report against the versioned, "
    "deterministic rule set (never an LLM) and returns PASS/WARN/BLOCK. "
    "Retrying the same inputs at the current engine version returns the "
    "existing assessment rather than creating a duplicate.",
)
async def create_risk_assessment(
    project_id: uuid.UUID, payload: RiskAssessmentCreateRequest, service: ServiceDep
) -> RiskAssessmentResponse:
    record = await service.run_assessment(
        project_id,
        compatibility_scan_id=payload.compatibility_scan_id,
        differential_report_id=payload.differential_report_id,
    )
    return RiskAssessmentResponse.from_record(record)


@router.get(
    "/assessments/{assessment_id}",
    response_model=RiskAssessmentResponse,
    dependencies=[_READ],
)
async def get_risk_assessment(
    project_id: uuid.UUID, assessment_id: uuid.UUID, service: ServiceDep
) -> RiskAssessmentResponse:
    record = await service.get_assessment(project_id, assessment_id)
    return RiskAssessmentResponse.from_record(record)


@router.get("/assessments", response_model=RiskAssessmentListResponse, dependencies=[_READ])
async def list_risk_assessments(
    project_id: uuid.UUID,
    service: ServiceDep,
    page: int = 1,
    page_size: int = 20,
) -> RiskAssessmentListResponse:
    result = await service.list_assessments(project_id, page=page, page_size=page_size)
    return RiskAssessmentListResponse(
        items=[RiskAssessmentListItemResponse.from_record(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
