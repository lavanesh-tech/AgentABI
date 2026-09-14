"""DifferentialService — loads two replays, validates them, runs the
pure `app.differential.analyzer`, persists the result, and returns it
(spec §18). The only place `app/differential/` evidence is ever
persisted; the analyzer itself never touches the database.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.differential.analyzer import ANALYZER_VERSION, analyze
from app.differential.models import DifferentialReport as PureDifferentialReport
from app.differential.models import ReplayStepView
from app.domain.checksums import compute_checksum
from app.domain.exceptions import (
    DifferentialReportNotFound,
    ReplayNotFound,
    ReplayNotReadyForDifferential,
)
from app.models.differential_change import DifferentialChangeRecord
from app.models.differential_report import DifferentialReportRecord
from app.models.replay_run import ReplayRun
from app.models.replay_step import ReplayStep
from app.replay.models import ReplayStatus
from app.repositories.differential_repository import DifferentialRepository
from app.repositories.replay_repository import ReplayRepository


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int


class DifferentialService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._differentials = DifferentialRepository(session)
        self._replays = ReplayRepository(session)

    async def run_analysis(
        self,
        project_id: uuid.UUID,
        *,
        baseline_replay_id: uuid.UUID,
        candidate_replay_id: uuid.UUID,
        compatibility_scan_id: uuid.UUID | None = None,
    ) -> DifferentialReportRecord:
        # Idempotency first (spec §19) — a retry of the same logical
        # comparison at the current analyzer version returns the
        # existing report rather than creating a duplicate.
        existing = await self._differentials.get_by_idempotency_key(
            project_id, baseline_replay_id, candidate_replay_id, ANALYZER_VERSION
        )
        if existing is not None:
            return existing

        baseline_run = await self._get_ready_replay(project_id, baseline_replay_id)
        candidate_run = await self._get_ready_replay(project_id, candidate_replay_id)
        # Both loaded scoped to the same `project_id` (spec §23): a
        # replay belonging to another project/org simply doesn't
        # resolve — `ReplayNotFound`, never a cross-tenant comparison.

        baseline_views = [_to_view(step) for step in baseline_run.steps]
        candidate_views = [_to_view(step) for step in candidate_run.steps]

        report = analyze(baseline_views, candidate_views)

        record = _to_record(
            report,
            organization_id=baseline_run.organization_id,
            project_id=project_id,
            baseline_replay_id=baseline_replay_id,
            candidate_replay_id=candidate_replay_id,
            compatibility_scan_id=compatibility_scan_id,
        )
        self._differentials.add(record)
        await self._session.flush()
        await self._session.refresh(record, attribute_names=["changes"])
        return record

    async def get_report(
        self, project_id: uuid.UUID, report_id: uuid.UUID
    ) -> DifferentialReportRecord:
        report = await self._differentials.get_by_id(project_id, report_id)
        if report is None:
            raise DifferentialReportNotFound(report_id)
        return report

    async def list_reports(
        self, project_id: uuid.UUID, *, page: int = 1, page_size: int = 20
    ) -> Page[DifferentialReportRecord]:
        offset = (page - 1) * page_size
        items, total = await self._differentials.list_by_project(
            project_id, offset=offset, limit=page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def _get_ready_replay(self, project_id: uuid.UUID, replay_id: uuid.UUID) -> ReplayRun:
        replay = await self._replays.get_by_id(project_id, replay_id)
        if replay is None:
            raise ReplayNotFound(replay_id)
        if replay.status != ReplayStatus.COMPLETED:
            raise ReplayNotReadyForDifferential(replay_id, replay.status)
        return replay


def _to_view(step: ReplayStep) -> ReplayStepView:
    return ReplayStepView(
        id=step.id,
        sequence_number=step.sequence_number,
        source_event_id=step.source_event_id,
        kind=step.kind.value,
        status=step.status.value,
        component_id=step.component_id,
        component_version_id=step.component_version_id,
        input=step.input,
        output=step.output,
        error=step.error,
        duration_ms=step.duration_ms,
    )


def _to_record(
    report: PureDifferentialReport,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    baseline_replay_id: uuid.UUID,
    candidate_replay_id: uuid.UUID,
    compatibility_scan_id: uuid.UUID | None,
) -> DifferentialReportRecord:
    summary = report.summary
    content_hash = compute_checksum(_canonical_report_dict(report))

    record = DifferentialReportRecord(
        organization_id=organization_id,
        project_id=project_id,
        baseline_replay_id=baseline_replay_id,
        candidate_replay_id=candidate_replay_id,
        compatibility_scan_id=compatibility_scan_id,
        analyzer_version=report.analyzer_version,
        total_baseline_steps=summary.total_baseline_steps,
        total_candidate_steps=summary.total_candidate_steps,
        matched_steps=summary.matched_steps,
        added_steps=summary.added_steps,
        removed_steps=summary.removed_steps,
        changed_steps=summary.changed_steps,
        new_failures=summary.new_failures,
        resolved_failures=summary.resolved_failures,
        changed_outputs=summary.changed_outputs,
        schema_changes=summary.schema_changes,
        content_hash=content_hash,
    )
    record.changes = [
        _to_change_record(index, sd) for index, sd in enumerate(report.step_differences)
    ]
    return record


def _to_change_record(order_index: int, sd) -> DifferentialChangeRecord:  # noqa: ANN001
    latency = sd.latency_difference
    error = sd.error_difference
    return DifferentialChangeRecord(
        order_index=order_index,
        alignment_method=sd.alignment_method.value,
        difference_types=[dt.value for dt in sd.difference_types],
        sequence_number=sd.sequence_number,
        baseline_step_id=sd.baseline.id if sd.baseline else None,
        candidate_step_id=sd.candidate.id if sd.candidate else None,
        baseline_status=sd.baseline.status if sd.baseline else None,
        candidate_status=sd.candidate.status if sd.candidate else None,
        output_differences=[
            {
                "difference_type": fd.difference_type.value,
                "path": fd.path,
                "old_value": fd.old_value,
                "new_value": fd.new_value,
                "redacted": fd.redacted,
                "evidence": fd.evidence,
            }
            for fd in sd.output_differences
        ],
        error_difference=(
            {
                "difference_type": error.difference_type.value,
                "baseline_present": error.baseline_present,
                "candidate_present": error.candidate_present,
                "baseline_category": error.baseline_category,
                "candidate_category": error.candidate_category,
            }
            if error is not None
            else None
        ),
        latency_delta_ms=latency.delta_ms if latency else None,
        latency_percent_delta=latency.percent_delta if latency else None,
    )


def _canonical_report_dict(report: PureDifferentialReport) -> dict:
    """A plain, deterministic dict of the report's content for hashing
    (spec §34) — same canonicalization approach as
    `app.domain.checksums` (sorted keys downstream), built from the
    already-deterministically-ordered `step_differences` tuple."""

    return {
        "analyzer_version": report.analyzer_version,
        "summary": {
            "total_baseline_steps": report.summary.total_baseline_steps,
            "total_candidate_steps": report.summary.total_candidate_steps,
            "matched_steps": report.summary.matched_steps,
            "added_steps": report.summary.added_steps,
            "removed_steps": report.summary.removed_steps,
            "changed_steps": report.summary.changed_steps,
            "new_failures": report.summary.new_failures,
            "resolved_failures": report.summary.resolved_failures,
            "changed_outputs": report.summary.changed_outputs,
            "schema_changes": report.summary.schema_changes,
        },
        "step_differences": [
            {
                "alignment_method": sd.alignment_method.value,
                "difference_types": [dt.value for dt in sd.difference_types],
                "sequence_number": sd.sequence_number,
            }
            for sd in report.step_differences
        ],
    }
