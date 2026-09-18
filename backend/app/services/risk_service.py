"""RiskService — loads a compatibility scan and/or a differential
report scoped to the project, attempts a blast-radius lookup (degrading
gracefully if the graph is unreachable), builds a `RiskContext` from
that deterministic evidence ONLY, runs the pure `app.risk.engine`, and
persists the immutable result (Phase 11 spec §23-§27).

This is the only place a `RiskContext` is constructed and the only
place a `RiskAssessmentRecord` is written. It never imports `app.llm`
or anything OpenAI-shaped — see `tests/test_risk_architectural_
invariant.py`.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.compatibility.models import Severity
from app.core.config import get_settings
from app.differential.models import DifferenceType
from app.domain.checksums import compute_checksum
from app.domain.exceptions import (
    CompatibilityScanNotFound,
    DifferentialReportNotFound,
    GraphComponentNotFound,
    GraphUnavailable,
    ProjectNotFound,
    RiskAssessmentInputRequired,
    RiskAssessmentNotFound,
)
from app.models.compatibility_scan import CompatibilityScan
from app.models.differential_report import DifferentialReportRecord
from app.models.risk_assessment import RiskAssessmentRecord
from app.models.risk_rule_result import RiskRuleResultRecord
from app.observability import record_analysis_run, record_risk_decision, start_span
from app.repositories.compatibility_scan_repository import CompatibilityScanRepository
from app.repositories.differential_repository import DifferentialRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.risk_repository import RiskRepository
from app.risk.engine import RISK_ENGINE_VERSION, evaluate
from app.risk.models import RiskAssessment as PureRiskAssessment
from app.risk.models import RiskContext, TriggeredRule
from app.services.blast_radius import BlastRadiusService

_TOOL_CHANGE_TYPES = {
    DifferenceType.TOOL_CHANGED.value,
    DifferenceType.PROVIDER_INVOCATION_CHANGED.value,
}
_NON_SUCCESSFUL_STATUSES = {"failed", "skipped"}


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int


class RiskService:
    def __init__(
        self, session: AsyncSession, blast_radius: BlastRadiusService | None = None
    ) -> None:
        self._session = session
        self._risk = RiskRepository(session)
        self._scans = CompatibilityScanRepository(session)
        self._differentials = DifferentialRepository(session)
        self._projects = ProjectRepository(session)
        self._blast_radius = blast_radius

    async def run_assessment(
        self,
        project_id: uuid.UUID,
        *,
        compatibility_scan_id: uuid.UUID | None = None,
        differential_report_id: uuid.UUID | None = None,
    ) -> RiskAssessmentRecord:
        """Phase 15 spec §14/§15 domain span boundary — wraps
        `_run_assessment_impl` at the service boundary rather than
        importing OpenTelemetry into `app/risk/`'s pure engine."""

        settings = get_settings()
        start = time.monotonic()
        status = "success"
        with start_span(
            "agentabi.risk.evaluate",
            attributes={
                "agentabi.project_id": str(project_id),
                "agentabi.compatibility_scan_id": str(compatibility_scan_id)
                if compatibility_scan_id
                else None,
                "agentabi.differential_report_id": str(differential_report_id)
                if differential_report_id
                else None,
            },
        ) as span:
            try:
                record = await self._run_assessment_impl(
                    project_id,
                    compatibility_scan_id=compatibility_scan_id,
                    differential_report_id=differential_report_id,
                )
            except Exception:
                status = "failure"
                raise
            finally:
                record_analysis_run(
                    settings,
                    pipeline="risk",
                    status=status,
                    duration_seconds=time.monotonic() - start,
                )
            if span is not None:
                span.set_attribute("agentabi.risk_decision", record.decision)
                span.set_attribute("agentabi.risk_score", record.score)
            # Mandatory (spec §8/§38): observed exactly as produced by
            # the deterministic risk engine via _run_assessment_impl above —
            # never recalculated or re-derived here.
            record_risk_decision(
                settings,
                decision=record.decision,
                hard_block=record.hard_block,
                score=record.score,
            )
            return record

    async def _run_assessment_impl(
        self,
        project_id: uuid.UUID,
        *,
        compatibility_scan_id: uuid.UUID | None = None,
        differential_report_id: uuid.UUID | None = None,
    ) -> RiskAssessmentRecord:
        if compatibility_scan_id is None and differential_report_id is None:
            raise RiskAssessmentInputRequired()

        # Idempotency first (spec §23), same posture as
        # `DifferentialService.run_analysis` (Phase 10).
        existing = await self._risk.get_by_idempotency_key(
            project_id, compatibility_scan_id, differential_report_id, RISK_ENGINE_VERSION
        )
        if existing is not None:
            return existing

        scan: CompatibilityScan | None = None
        if compatibility_scan_id is not None:
            scan = await self._scans.get_by_id(project_id, compatibility_scan_id)
            if scan is None:
                raise CompatibilityScanNotFound(compatibility_scan_id)

        report: DifferentialReportRecord | None = None
        if differential_report_id is not None:
            report = await self._differentials.get_by_id(project_id, differential_report_id)
            if report is None:
                raise DifferentialReportNotFound(differential_report_id)

        blast_radius_total: int | None = await self._compute_blast_radius(project_id, scan)

        context = _build_context(scan, report, blast_radius_total)
        assessment = evaluate(context)

        # `CompatibilityScan` doesn't denormalize `organization_id`
        # (only `project_id`); `DifferentialReportRecord` does. Prefer
        # the report's when available, otherwise resolve it from the
        # project — never fabricated, never guessed.
        organization_id = report.organization_id if report is not None else None
        if organization_id is None:
            project = await self._projects.get_by_id(project_id)
            if project is None:
                raise ProjectNotFound(project_id)
            organization_id = project.organization_id

        record = _to_record(
            assessment,
            organization_id=organization_id,
            project_id=project_id,
            compatibility_scan_id=compatibility_scan_id,
            differential_report_id=differential_report_id,
        )
        self._risk.add(record)
        await self._session.flush()
        await self._session.refresh(record, attribute_names=["rule_results"])
        return record

    async def get_assessment(
        self, project_id: uuid.UUID, assessment_id: uuid.UUID
    ) -> RiskAssessmentRecord:
        record = await self._risk.get_by_id(project_id, assessment_id)
        if record is None:
            raise RiskAssessmentNotFound(assessment_id)
        return record

    async def list_assessments(
        self, project_id: uuid.UUID, *, page: int = 1, page_size: int = 20
    ) -> Page[RiskAssessmentRecord]:
        offset = (page - 1) * page_size
        items, total = await self._risk.list_by_project(project_id, offset=offset, limit=page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def _compute_blast_radius(
        self, project_id: uuid.UUID, scan: CompatibilityScan | None
    ) -> int | None:
        """Best-effort only (spec §14): a graph that is unreachable, or a
        component that was never synced into it, is "no signal" — never
        a hard failure of the risk assessment as a whole, and never
        coerced to 0 ("nothing affected"), which would be a fabricated
        finding."""

        if scan is None or self._blast_radius is None:
            return None
        try:
            result = await self._blast_radius.compute(project_id, scan.component_id)
        except (GraphUnavailable, GraphComponentNotFound):
            return None
        return result.total_affected


def _build_context(
    scan: CompatibilityScan | None,
    report: DifferentialReportRecord | None,
    blast_radius_total: int | None,
) -> RiskContext:
    compatibility_status = (
        scan.status.value
        if scan is not None and hasattr(scan.status, "value")
        else str(scan.status)
        if scan is not None
        else None
    )
    compatibility_breaking_count = scan.breaking_count if scan is not None else 0
    compatibility_critical_count = (
        sum(1 for c in scan.changes if c.severity == Severity.CRITICAL) if scan is not None else 0
    )

    if report is None:
        return RiskContext(
            compatibility_status=compatibility_status,
            compatibility_breaking_count=compatibility_breaking_count,
            compatibility_critical_count=compatibility_critical_count,
            blast_radius_total_affected=blast_radius_total,
            compatibility_scan_id=scan.id if scan is not None else None,
        )

    has_removed_required_step = any(
        DifferenceType.STEP_REMOVED.value in c.difference_types
        and c.baseline_status is not None
        and c.baseline_status not in _NON_SUCCESSFUL_STATUSES
        for c in report.changes
    )
    tool_invocation_changed = any(
        any(dt in _TOOL_CHANGE_TYPES for dt in c.difference_types) for c in report.changes
    )
    error_introduced = any(
        DifferenceType.ERROR_INTRODUCED.value in c.difference_types for c in report.changes
    )
    latency_deltas = [
        c.latency_percent_delta for c in report.changes if c.latency_percent_delta is not None
    ]
    max_latency_percent_delta = max(latency_deltas) if latency_deltas else None

    return RiskContext(
        compatibility_status=compatibility_status,
        compatibility_breaking_count=compatibility_breaking_count,
        compatibility_critical_count=compatibility_critical_count,
        differential_available=True,
        new_failures=report.new_failures,
        resolved_failures=report.resolved_failures,
        changed_outputs=report.changed_outputs,
        schema_changes=report.schema_changes,
        removed_steps=report.removed_steps,
        has_removed_required_step=has_removed_required_step,
        tool_invocation_changed=tool_invocation_changed,
        error_introduced=error_introduced,
        max_latency_percent_delta=max_latency_percent_delta,
        blast_radius_total_affected=blast_radius_total,
        compatibility_scan_id=scan.id if scan is not None else None,
        differential_report_id=report.id,
    )


def _to_record(
    assessment: PureRiskAssessment,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    compatibility_scan_id: uuid.UUID | None,
    differential_report_id: uuid.UUID | None,
) -> RiskAssessmentRecord:
    content_hash = compute_checksum(_canonical_assessment_dict(assessment))
    record = RiskAssessmentRecord(
        organization_id=organization_id,
        project_id=project_id,
        compatibility_scan_id=compatibility_scan_id,
        differential_report_id=differential_report_id,
        risk_engine_version=assessment.risk_engine_version,
        decision=assessment.decision.value,
        score=assessment.score,
        hard_block=assessment.hard_block,
        content_hash=content_hash,
    )
    record.rule_results = [
        _to_rule_result_record(index, rule) for index, rule in enumerate(assessment.triggered_rules)
    ]
    return record


def _to_rule_result_record(order_index: int, rule: TriggeredRule) -> RiskRuleResultRecord:
    return RiskRuleResultRecord(
        order_index=order_index,
        rule_id=rule.rule_id,
        category=rule.category.value,
        description=rule.description,
        score_delta=rule.score_delta,
        evidence_refs=list(rule.evidence_refs),
        hard_block=rule.hard_block,
    )


def _canonical_assessment_dict(assessment: PureRiskAssessment) -> dict[str, Any]:
    """A plain, deterministic dict of the assessment's content for
    hashing (spec §33's reproducibility requirement) — same
    canonicalization approach as `DifferentialService`'s
    `_canonical_report_dict` (Phase 10)."""

    return {
        "risk_engine_version": assessment.risk_engine_version,
        "decision": assessment.decision.value,
        "score": assessment.score,
        "hard_block": assessment.hard_block,
        "triggered_rules": [
            {
                "rule_id": r.rule_id,
                "category": r.category.value,
                "score_delta": r.score_delta,
                "hard_block": r.hard_block,
            }
            for r in assessment.triggered_rules
        ],
    }
