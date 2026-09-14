"""GitHubPullRequestAnalysisService — the Phase 12/13 orchestration
service. Resolves the repository mapping, starts/reuses a logical
analysis for the PR's exact `head_sha`, runs the existing deterministic
pipeline (Phase 5 compatibility -> Phase 11 risk — see docs/DECISIONS.md
for why Phase 7/10 replay/differential aren't wired into this call path
yet), and publishes the result to GitHub via the injected
`GitHubChecksClient`.

No comparison/scoring logic lives here — `CompatibilityService`/
`RiskService` own that; this module is pipeline glue, persistence of PR-
analysis lifecycle state, and check publishing only (spec §18: "do not
duplicate Phase 5/7/10/11 logic").

Phase 13 splits the old single `analyze_pull_request` call into two
steps so the deterministic pipeline can run off the webhook request
thread when `KAFKA_ENABLED=true`:

- `start_analysis` — cheap, synchronous: resolve the mapping, check
  idempotency, persist a PENDING `GitHubPullRequestAnalysis` row. This
  is all `app/api/v1/github_webhook.py` calls directly; with Kafka
  enabled it then publishes an analysis-request event instead of
  continuing.
- `run_analysis` — the actual pipeline: compatibility scan, risk
  assessment, check publishing. Called either inline right after
  `start_analysis` (Kafka disabled — `analyze_pull_request` below is
  the same combined call Phase 12 always made) or from
  `app/kafka/analysis_handler.py` when a worker consumes the request
  event.

`run_analysis` is itself idempotent (spec §17/§37): a redelivered event
for an already-COMPLETED/FAILED analysis is a no-op; a redelivered event
for a PUBLISH_FAILED analysis retries the check publish only, never
recomputing risk (spec §28's "never recompute risk solely because
publishing failed").
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.compatibility.models import CompatibilityStatus
from app.domain.exceptions import (
    ComponentVersionNotFound,
    GitHubAnalysisHeadShaMismatch,
    GitHubAPIUnavailable,
    GitHubAuthenticationFailed,
    GitHubCheckPublishFailed,
    GitHubPullRequestAnalysisNotFound,
    GitHubRepositoryNotMapped,
    MissingAgentABIConfiguration,
)
from app.github.check_mapping import (
    CHECK_NAME,
    build_completed_output,
    build_in_progress_output,
    decision_to_conclusion,
)
from app.github.checks_models import (
    CheckRunRequest,
    CheckStatus,
    GitHubChecksClient,
)
from app.github.pr_analysis_models import GitHubPRAnalysisStatus
from app.github.pr_webhook_models import PullRequestWebhookPayload
from app.models.compatibility_scan import CompatibilityScan
from app.models.github_pr_analysis import GitHubPullRequestAnalysis
from app.models.github_repository_mapping import GitHubRepositoryMapping
from app.models.risk_assessment import RiskAssessmentRecord
from app.observability import start_span
from app.repositories.github_pr_analysis_repository import GitHubPRAnalysisRepository
from app.repositories.github_repository_mapping_repository import (
    GitHubRepositoryMappingRepository,
)
from app.risk.models import RiskDecision
from app.services.audit_service import AuditService
from app.services.compatibility_service import CompatibilityService
from app.services.component_registry import ComponentRegistryService
from app.services.risk_service import RiskService

# Bumped whenever the orchestration itself changes what "the same
# logical analysis" means (e.g. wiring in replay/differential evidence
# later) — independent of `RISK_ENGINE_VERSION`/`ANALYZER_VERSION`,
# which version the deterministic engines that feed it.
ANALYSIS_VERSION = "1"

_GITHUB_ORCHESTRATABLE_ERRORS = (
    GitHubAPIUnavailable,
    GitHubAuthenticationFailed,
    GitHubCheckPublishFailed,
)

# Analyses in these states are done — a redelivered request event never
# re-runs the pipeline for them (spec §17: consumers must be idempotent
# under Kafka's at-least-once delivery).
_TERMINAL_STATUSES = frozenset(
    {GitHubPRAnalysisStatus.COMPLETED.value, GitHubPRAnalysisStatus.FAILED.value}
)


@dataclass(frozen=True)
class PRAnalysisPage:
    items: list[GitHubPullRequestAnalysis]
    total: int
    page: int
    page_size: int


class GitHubPullRequestAnalysisService:
    def __init__(self, session: AsyncSession, *, checks_client: GitHubChecksClient) -> None:
        self._session = session
        self._mappings = GitHubRepositoryMappingRepository(session)
        self._analyses = GitHubPRAnalysisRepository(session)
        self._registry = ComponentRegistryService(session)
        self._compatibility = CompatibilityService(session)
        self._risk = RiskService(session)
        self._audit = AuditService(session)
        self._checks_client = checks_client

    async def analyze_pull_request(
        self,
        payload: PullRequestWebhookPayload,
        *,
        delivery_id: str,
        request_id: str | None = None,
    ) -> GitHubPullRequestAnalysis:
        """The direct/synchronous path (`KAFKA_ENABLED=false`) — start
        then immediately run, exactly what Phase 12 always did as one
        call."""

        analysis, created = await self._start_or_get(
            payload, delivery_id=delivery_id, request_id=request_id
        )
        if not created:
            return analysis
        return await self.run_analysis(
            project_id=analysis.project_id,
            analysis_id=analysis.id,
            expected_head_sha=analysis.head_sha,
        )

    async def start_analysis(
        self,
        payload: PullRequestWebhookPayload,
        *,
        delivery_id: str,
        request_id: str | None = None,
    ) -> GitHubPullRequestAnalysis:
        """The `KAFKA_ENABLED=true` path's first (and only synchronous)
        step: validate the mapping/config exists and persist a PENDING
        row — cheap enough to run on the webhook request thread. The
        caller (the webhook route) publishes an analysis-request event
        for this row and returns; `run_analysis` does the actual work,
        later, in a worker."""

        analysis, _created = await self._start_or_get(
            payload, delivery_id=delivery_id, request_id=request_id
        )
        return analysis

    async def list_analyses(
        self,
        project_id: uuid.UUID,
        *,
        pull_request_number: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PRAnalysisPage:
        """Phase 14 read path (spec §25/§26) — the frontend's only source
        for PR-analysis history; no read path existed before this."""

        offset = (page - 1) * page_size
        items, total = await self._analyses.list_by_project(
            project_id,
            pull_request_number=pull_request_number,
            offset=offset,
            limit=page_size,
        )
        return PRAnalysisPage(items=items, total=total, page=page, page_size=page_size)

    async def get_analysis(
        self, project_id: uuid.UUID, analysis_id: uuid.UUID
    ) -> GitHubPullRequestAnalysis:
        analysis = await self._analyses.get_by_id(project_id, analysis_id)
        if analysis is None:
            raise GitHubPullRequestAnalysisNotFound(analysis_id)
        return analysis

    async def get_repository_mapping(
        self, github_repository_id: int
    ) -> GitHubRepositoryMapping | None:
        """Exposed so a caller building an analysis-request event can
        include `component_id`/`baseline_version` (spec §14) without
        duplicating the repository lookup."""

        return await self._mappings.get_by_github_repository_id(github_repository_id)

    async def _start_or_get(
        self,
        payload: PullRequestWebhookPayload,
        *,
        delivery_id: str,
        request_id: str | None,
    ) -> tuple[GitHubPullRequestAnalysis, bool]:
        mapping = await self._mappings.get_by_github_repository_id(payload.repository_id)
        if mapping is None:
            raise GitHubRepositoryNotMapped(payload.repository_id)
        if mapping.component_id is None:
            raise MissingAgentABIConfiguration(
                f"repository {payload.repository_full_name} is mapped to a project but has "
                "no component_id configured"
            )

        existing = await self._analyses.get_by_idempotency_key(
            payload.repository_id, payload.pull_request_number, payload.head_sha, ANALYSIS_VERSION
        )
        if existing is not None:
            # Idempotent (spec §23/§24 from Phase 12, spec §17 from
            # Phase 13): a redelivered webhook for a commit already
            # analyzed reuses the existing row, never a duplicate.
            return existing, False

        analysis = GitHubPullRequestAnalysis(
            organization_id=mapping.organization_id,
            project_id=mapping.project_id,
            github_repository_id=payload.repository_id,
            pull_request_number=payload.pull_request_number,
            head_sha=payload.head_sha,
            base_sha=payload.base_sha,
            delivery_id=delivery_id,
            analysis_version=ANALYSIS_VERSION,
            status=GitHubPRAnalysisStatus.PENDING.value,
        )
        self._analyses.add(analysis)
        await self._session.flush()
        self._audit.record(
            action=AuditAction.GITHUB_PR_ANALYSIS_STARTED,
            organization_id=mapping.organization_id,
            resource_type="github_pr_analysis",
            resource_id=analysis.id,
            request_id=request_id,
            metadata={
                "project_id": str(mapping.project_id),
                "github_repository_id": payload.repository_id,
                "pull_request_number": payload.pull_request_number,
                "head_sha": payload.head_sha,
            },
        )
        await self._session.commit()
        return analysis, True

    async def run_analysis(
        self,
        *,
        project_id: Any,
        analysis_id: Any,
        expected_head_sha: str,
    ) -> GitHubPullRequestAnalysis:
        """Phase 15 spec §14 domain span boundary — wraps the actual
        pipeline (`_run_analysis_impl`) rather than importing
        OpenTelemetry into the deterministic engines it calls."""

        with start_span(
            "agentabi.github.pr_analysis",
            attributes={
                "agentabi.project_id": str(project_id),
                "agentabi.github_pr_analysis_id": str(analysis_id),
                "agentabi.head_sha": expected_head_sha,
            },
        ):
            return await self._run_analysis_impl(
                project_id=project_id,
                analysis_id=analysis_id,
                expected_head_sha=expected_head_sha,
            )

    async def _run_analysis_impl(
        self,
        *,
        project_id: Any,
        analysis_id: Any,
        expected_head_sha: str,
    ) -> GitHubPullRequestAnalysis:
        """Runs (or safely no-ops on) the deterministic pipeline for one
        persisted `GitHubPullRequestAnalysis` row. Called inline by
        `analyze_pull_request` (Kafka disabled) or by `app/kafka/
        analysis_handler.py` (Kafka enabled, consuming a request event).

        `expected_head_sha` is the head_sha the *caller* believes this
        analysis is for (the event payload's `head_sha`, or the
        just-created row's own `head_sha` on the direct path) — checked
        against the persisted, immutable `analysis.head_sha` before any
        work happens (spec §16/§38's mandatory stale-SHA protection).
        Since a row's `head_sha` is never reassigned, a mismatch here
        would mean a caller is misusing an analysis id for the wrong
        commit, not a legitimate race — see `GitHubAnalysisHeadShaMismatch`.
        """

        analysis = await self._analyses.get_by_id(project_id, analysis_id)
        if analysis is None:
            raise GitHubPullRequestAnalysisNotFound(analysis_id)
        if analysis.head_sha != expected_head_sha:
            raise GitHubAnalysisHeadShaMismatch(analysis_id, expected_head_sha, analysis.head_sha)

        if analysis.status in _TERMINAL_STATUSES:
            # COMPLETED: idempotent no-op on redelivery (spec §17/§37).
            # FAILED: a permanent pipeline failure is not auto-retried by
            # a redelivered event (spec §20 — never retry a permanent
            # validation error indefinitely); a fresh delivery is needed.
            return analysis

        mapping = await self._mappings.get_by_github_repository_id(analysis.github_repository_id)
        if mapping is None:
            # Defensive only — `start_analysis` already required a
            # mapping to exist to create this row in the first place.
            raise GitHubRepositoryNotMapped(analysis.github_repository_id)

        if (
            analysis.status == GitHubPRAnalysisStatus.PUBLISH_FAILED.value
            and analysis.risk_assessment_id is not None
        ):
            # Retry the check publish only — deterministic evidence
            # already exists and is never recomputed (spec §28).
            scan = await self._session.get(CompatibilityScan, analysis.compatibility_scan_id)
            assessment = await self._session.get(RiskAssessmentRecord, analysis.risk_assessment_id)
            if scan is not None and assessment is not None:
                await self._publish_result(mapping, analysis, scan, assessment)
                return analysis

        analysis.status = GitHubPRAnalysisStatus.IN_PROGRESS.value
        await self._session.flush()
        await self._session.commit()

        await self._publish_in_progress(mapping, analysis)

        try:
            scan = await self._run_compatibility(mapping, analysis.head_sha)
            assessment = await self._risk.run_assessment(
                mapping.project_id, compatibility_scan_id=scan.id
            )
        except Exception:
            analysis.status = GitHubPRAnalysisStatus.FAILED.value
            await self._session.flush()
            await self._session.commit()
            raise

        analysis.compatibility_scan_id = scan.id
        analysis.risk_assessment_id = assessment.id
        analysis.decision = assessment.decision
        analysis.status = GitHubPRAnalysisStatus.COMPLETED.value
        analysis.completed_at = datetime.now(UTC)
        await self._session.flush()
        self._audit.record(
            action=AuditAction.GITHUB_PR_ANALYSIS_COMPLETED,
            organization_id=mapping.organization_id,
            resource_type="github_pr_analysis",
            resource_id=analysis.id,
            metadata={
                "project_id": str(mapping.project_id),
                "risk_assessment_id": str(assessment.id),
                "decision": assessment.decision,
            },
        )
        # Deterministic evidence is committed BEFORE any GitHub publish
        # attempt (spec §28): a publish failure below can never corrupt
        # or roll back the risk assessment that already exists.
        await self._session.commit()

        await self._publish_result(mapping, analysis, scan, assessment)
        return analysis

    async def _run_compatibility(
        self, mapping: GitHubRepositoryMapping, head_sha: str
    ) -> CompatibilityScan:
        if mapping.baseline_version:
            baseline_version = mapping.baseline_version
        else:
            try:
                baseline = await self._registry.get_latest_component_version(
                    mapping.project_id,
                    mapping.component_id,  # type: ignore[arg-type]
                )
            except ComponentVersionNotFound as exc:
                raise MissingAgentABIConfiguration(
                    "no baseline_version configured and no ComponentVersion registered yet "
                    f"for component {mapping.component_id}"
                ) from exc
            baseline_version = baseline.version

        try:
            return await self._compatibility.run_scan(
                mapping.project_id,
                mapping.component_id,  # type: ignore[arg-type]
                baseline_version,
                head_sha,
            )
        except ComponentVersionNotFound as exc:
            # Spec §19/§21: never infer a candidate version from a raw
            # diff — the caller's CI must register a `ComponentVersion`
            # whose `version` equals this PR's head_sha before (or as
            # part of) triggering analysis.
            raise MissingAgentABIConfiguration(
                f"no ComponentVersion registered with version={head_sha!r} for component "
                f"{mapping.component_id}; register one before triggering PR analysis"
            ) from exc

    async def _publish_in_progress(
        self, mapping: GitHubRepositoryMapping, analysis: GitHubPullRequestAnalysis
    ) -> None:
        # Best-effort (spec §11's "if awkward, at minimum publish a
        # completed check cleanly"): a failure here never blocks the
        # deterministic pipeline from running — it only means the final
        # `_publish_result` call falls back to creating a fresh check
        # run instead of updating this one.
        request = CheckRunRequest(
            repository_full_name=mapping.github_repository_full_name,
            head_sha=analysis.head_sha,
            name=CHECK_NAME,
            status=CheckStatus.IN_PROGRESS,
            output=build_in_progress_output(compatibility_summary=None),
            external_id=str(analysis.id),
        )
        try:
            result = await self._checks_client.create_check_run(request)
        except _GITHUB_ORCHESTRATABLE_ERRORS:
            return
        analysis.check_run_id = result.id
        await self._session.flush()
        await self._session.commit()

    async def _publish_result(
        self,
        mapping: GitHubRepositoryMapping,
        analysis: GitHubPullRequestAnalysis,
        scan: CompatibilityScan,
        assessment: RiskAssessmentRecord,
    ) -> None:
        # Every publish call is keyed off `analysis.head_sha` — never a
        # "latest"/externally-passed value — which is what makes the
        # exact-SHA invariant hold structurally (spec §16/§25): this
        # row's check can never be mistaken for a different commit's.
        decision = RiskDecision(assessment.decision)
        conclusion = decision_to_conclusion(decision)
        top_rules = [(r.rule_id, r.score_delta) for r in assessment.rule_results]
        output = build_completed_output(
            decision=decision,
            score=assessment.score,
            risk_engine_version=assessment.risk_engine_version,
            hard_block=assessment.hard_block,
            top_rules=top_rules,
            compatibility_summary=_compatibility_summary(scan),
        )
        request = CheckRunRequest(
            repository_full_name=mapping.github_repository_full_name,
            head_sha=analysis.head_sha,
            name=CHECK_NAME,
            status=CheckStatus.COMPLETED,
            output=output,
            conclusion=conclusion,
            external_id=str(analysis.id),
        )

        try:
            if analysis.check_run_id is not None:
                result = await self._checks_client.update_check_run(
                    repository_full_name=mapping.github_repository_full_name,
                    check_run_id=analysis.check_run_id,
                    request=request,
                )
            else:
                result = await self._checks_client.create_check_run(request)
        except _GITHUB_ORCHESTRATABLE_ERRORS as exc:
            analysis.status = GitHubPRAnalysisStatus.PUBLISH_FAILED.value
            analysis.publish_error = str(exc)[:500]
            await self._session.flush()
            self._audit.record(
                action=AuditAction.GITHUB_CHECK_FAILED,
                organization_id=mapping.organization_id,
                resource_type="github_pr_analysis",
                resource_id=analysis.id,
                metadata={
                    "project_id": str(mapping.project_id),
                    "risk_assessment_id": str(assessment.id),
                    "decision": assessment.decision,
                },
            )
            await self._session.commit()
            raise

        analysis.check_run_id = result.id
        analysis.status = GitHubPRAnalysisStatus.COMPLETED.value
        await self._session.flush()
        self._audit.record(
            action=AuditAction.GITHUB_CHECK_PUBLISHED,
            organization_id=mapping.organization_id,
            resource_type="github_pr_analysis",
            resource_id=analysis.id,
            metadata={
                "project_id": str(mapping.project_id),
                "check_run_id": result.id,
                "decision": assessment.decision,
            },
        )
        await self._session.commit()


def _compatibility_summary(scan: CompatibilityScan) -> str:
    if scan.status is CompatibilityStatus.COMPATIBLE:
        return f"{scan.total_changes} change(s), all compatible."
    return (
        f"{scan.total_changes} change(s) — {scan.breaking_count} breaking, "
        f"{scan.potentially_breaking_count} potentially breaking."
    )


__all__ = ["ANALYSIS_VERSION", "GitHubPullRequestAnalysisService"]
