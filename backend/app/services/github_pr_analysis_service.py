"""GitHubPullRequestAnalysisService — the Phase 12 orchestration
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
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.compatibility.models import CompatibilityStatus
from app.domain.exceptions import (
    ComponentVersionNotFound,
    GitHubAPIUnavailable,
    GitHubAuthenticationFailed,
    GitHubCheckPublishFailed,
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
        request_id: str | None,
    ) -> GitHubPullRequestAnalysis:
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
            # Idempotent (spec §23/§24): a redelivered webhook for a
            # commit already analyzed never re-runs the pipeline or
            # republishes the check.
            return existing

        analysis = GitHubPullRequestAnalysis(
            organization_id=mapping.organization_id,
            project_id=mapping.project_id,
            github_repository_id=payload.repository_id,
            pull_request_number=payload.pull_request_number,
            head_sha=payload.head_sha,
            base_sha=payload.base_sha,
            delivery_id=delivery_id,
            analysis_version=ANALYSIS_VERSION,
            status=GitHubPRAnalysisStatus.IN_PROGRESS.value,
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

        await self._publish_in_progress(mapping, analysis)

        try:
            scan = await self._run_compatibility(mapping, payload.head_sha)
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
            request_id=request_id,
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
