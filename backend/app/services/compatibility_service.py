"""CompatibilityService — orchestrates a compatibility scan: load the
baseline/candidate `ComponentVersion` rows from Postgres, dispatch to the
pure `app.compatibility.analyzer.analyze()` engine, and persist the
result as an immutable `CompatibilityScan` + `ScanChange` rows.

No comparison logic lives here — this module is entirely SQLAlchemy/
orchestration; `app/compatibility/analyzer.py` (and everything it calls)
is the entire deterministic decision surface, and stays independently
testable without a database.
"""

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.compatibility.analyzer import analyze
from app.compatibility.models import Classification, Severity
from app.core.config import get_settings
from app.domain.exceptions import CompatibilityScanNotFound, InvalidCompatibilityComparison
from app.models.compatibility_scan import CompatibilityScan
from app.models.component import Component
from app.models.component_version import ComponentVersion
from app.models.scan_change import ScanChange
from app.observability import record_analysis_run, start_span
from app.repositories.compatibility_scan_repository import CompatibilityScanRepository
from app.services.component_registry import ComponentRegistryService, Page


class CompatibilityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._registry = ComponentRegistryService(session)
        self._scans = CompatibilityScanRepository(session)

    async def run_scan(
        self,
        project_id: uuid.UUID,
        component_id: uuid.UUID,
        baseline_version: str,
        candidate_version: str,
    ) -> CompatibilityScan:
        """The public entry point (backs `POST .../compatibility/scans`).
        A single `component_id` is used to look up both versions, which
        is what makes an "unrelated components" comparison structurally
        impossible through this path — see `_scan_from_versions` for the
        defense-in-depth check that also covers any future calling path
        that doesn't share that guarantee.
        """

        start = time.monotonic()
        status = "success"
        with start_span(
            "agentabi.compatibility.analyze",
            attributes={
                "agentabi.project_id": str(project_id),
                "agentabi.component_id": str(component_id),
                "agentabi.baseline_version": baseline_version,
                "agentabi.candidate_version": candidate_version,
            },
        ):
            try:
                component = await self._registry.get_component(project_id, component_id)
                baseline = await self._registry.get_component_version(
                    project_id, component_id, baseline_version
                )
                candidate = await self._registry.get_component_version(
                    project_id, component_id, candidate_version
                )
                return await self._scan_from_versions(project_id, component, baseline, candidate)
            except Exception:
                status = "failure"
                raise
            finally:
                record_analysis_run(
                    get_settings(),
                    pipeline="compatibility",
                    status=status,
                    duration_seconds=time.monotonic() - start,
                )

    async def _scan_from_versions(
        self,
        project_id: uuid.UUID,
        component: Component,
        baseline: ComponentVersion,
        candidate: ComponentVersion,
    ) -> CompatibilityScan:
        # Same-component rule (Phase 5 §19), enforced here regardless of
        # how the caller obtained the two versions — not only trusted
        # from `run_scan`'s single-`component_id` call shape.
        if baseline.component_id != candidate.component_id:
            raise InvalidCompatibilityComparison(
                f"baseline version {baseline.id} (component {baseline.component_id}) and "
                f"candidate version {candidate.id} (component {candidate.component_id}) "
                "belong to different components"
            )

        result = analyze(component.component_type, baseline.content, candidate.content)
        counts = result.classification_counts
        severities = result.severity_counts

        scan = CompatibilityScan(
            project_id=project_id,
            component_id=component.id,
            baseline_version_id=baseline.id,
            candidate_version_id=candidate.id,
            status=result.status,
            total_changes=result.total_changes,
            compatible_count=counts[Classification.COMPATIBLE.value],
            potentially_breaking_count=counts[Classification.POTENTIALLY_BREAKING.value],
            breaking_count=counts[Classification.BREAKING.value],
            severity_info_count=severities[Severity.INFO.value],
            severity_low_count=severities[Severity.LOW.value],
            severity_medium_count=severities[Severity.MEDIUM.value],
            severity_high_count=severities[Severity.HIGH.value],
            severity_critical_count=severities[Severity.CRITICAL.value],
        )
        self._scans.add(scan)
        await self._session.flush()  # assigns scan.id

        for index, change in enumerate(result.changes):
            self._scans.add_change(
                ScanChange(
                    scan_id=scan.id,
                    order_index=index,
                    change_type=change.change_type.value,
                    path=change.path,
                    classification=change.classification,
                    severity=change.severity,
                    message=change.message,
                    old_value=change.old_value,
                    new_value=change.new_value,
                    evidence=change.evidence or None,
                )
            )
        await self._session.flush()
        await self._session.refresh(scan, attribute_names=["changes"])
        return scan

    async def get_scan(self, project_id: uuid.UUID, scan_id: uuid.UUID) -> CompatibilityScan:
        scan = await self._scans.get_by_id(project_id, scan_id)
        if scan is None:
            raise CompatibilityScanNotFound(scan_id)
        return scan

    async def list_scans(
        self,
        project_id: uuid.UUID,
        *,
        component_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[CompatibilityScan]:
        offset = (page - 1) * page_size
        items, total = await self._scans.list_by_project(
            project_id, component_id, offset, page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    # Deliberately no `update_scan`/`delete_scan`: once created, a scan
    # and its changes are historical evidence (Phase 5 §17) — nothing in
    # this service can mutate one, and a database trigger (migration
    # 0003) blocks it even for a write that bypasses this service.
