"""`AnalysisRequestHandler` — the one `EventHandler` this phase ships
(Phase 13 spec §9/§15). Consumes `github.pr.analysis.requested`,
validates the envelope, loads the persisted `GitHubPullRequestAnalysis`
row, and drives `GitHubPullRequestAnalysisService.run_analysis` — the
exact same pipeline call `analyze_pull_request` makes inline when Kafka
is disabled. No compatibility/risk logic here; this is dispatch glue
(classify domain errors as transient/permanent for the consumer's retry
policy, optionally publish a result event) only.
"""

import structlog

from app.domain.exceptions import (
    GitHubAnalysisHeadShaMismatch,
    GitHubAPIUnavailable,
    GitHubAuthenticationFailed,
    GitHubCheckPublishFailed,
    GitHubPullRequestAnalysisNotFound,
    GitHubRepositoryNotMapped,
    MissingAgentABIConfiguration,
)
from app.events.analysis_events import (
    build_analysis_completed_event,
    build_analysis_failed_event,
    parse_analysis_requested_payload,
)
from app.events.envelope import EVENT_TYPE_ANALYSIS_REQUESTED, EventEnvelope, validate_event_version
from app.events.errors import PermanentEventProcessingError, TransientEventProcessingError
from app.events.publisher import EventPublisher
from app.github.checks_models import GitHubChecksClient
from app.github.pr_analysis_models import GitHubPRAnalysisStatus
from app.models.risk_assessment import RiskAssessmentRecord
from app.services.github_pr_analysis_service import GitHubPullRequestAnalysisService

logger = structlog.get_logger(__name__)


class AnalysisRequestHandler:
    def __init__(
        self,
        session,  # AsyncSession — untyped here to avoid importing sqlalchemy at module scope
        *,
        checks_client: GitHubChecksClient,
        result_publisher: EventPublisher | None = None,
    ) -> None:
        self._session = session
        self._service = GitHubPullRequestAnalysisService(session, checks_client=checks_client)
        self._result_publisher = result_publisher

    async def handle(self, event: EventEnvelope) -> None:
        if event.event_type != EVENT_TYPE_ANALYSIS_REQUESTED:
            raise PermanentEventProcessingError(f"unexpected event_type {event.event_type!r}")
        validate_event_version(event)
        payload = parse_analysis_requested_payload(event)
        organization_id = event.organization_id or ""

        try:
            analysis = await self._service.run_analysis(
                project_id=payload.project_id,
                analysis_id=payload.github_pr_analysis_id,
                expected_head_sha=payload.head_sha,
            )
        except GitHubAnalysisHeadShaMismatch as exc:
            # Spec §16/§38: this event is stale relative to the analysis
            # row it names — never process it as if it were current.
            # Permanent: retrying the identical event changes nothing.
            raise PermanentEventProcessingError(str(exc)) from exc
        except (GitHubPullRequestAnalysisNotFound, GitHubRepositoryNotMapped) as exc:
            raise PermanentEventProcessingError(str(exc)) from exc
        except MissingAgentABIConfiguration as exc:
            await self._publish_failure(
                payload, organization_id, error_category="missing_configuration"
            )
            raise PermanentEventProcessingError(str(exc)) from exc
        except (GitHubAuthenticationFailed, GitHubCheckPublishFailed) as exc:
            await self._publish_failure(
                payload, organization_id, error_category="github_publish_failed"
            )
            raise PermanentEventProcessingError(str(exc)) from exc
        except GitHubAPIUnavailable as exc:
            # Bounded-retry-worthy (spec §20) — the consumer decides how
            # many times, never this handler.
            raise TransientEventProcessingError(str(exc)) from exc

        if (
            analysis.status == GitHubPRAnalysisStatus.COMPLETED.value
            and analysis.risk_assessment_id is not None
        ):
            await self._publish_completed(payload, analysis, organization_id)
        # PUBLISH_FAILED is already recorded by the service itself
        # (audit + `publish_error`) — nothing further to publish here;
        # a later redelivery retries the publish, never fabricates a
        # completion event for a check that never actually posted.

    async def _publish_completed(self, payload, analysis, organization_id: str) -> None:
        if self._result_publisher is None:
            return
        assessment = await self._session.get(RiskAssessmentRecord, analysis.risk_assessment_id)
        event = build_analysis_completed_event(
            github_pr_analysis_id=payload.github_pr_analysis_id,
            project_id=payload.project_id,
            organization_id=organization_id,
            github_repository_id=payload.github_repository_id,
            pull_request_number=payload.pull_request_number,
            head_sha=analysis.head_sha,
            risk_assessment_id=str(analysis.risk_assessment_id),
            decision=analysis.decision or "",
            score=assessment.score if assessment is not None else 0,
            correlation_id=analysis.delivery_id,
        )
        try:
            await self._result_publisher.publish(event)
        except TransientEventProcessingError:
            logger.warning(
                "github_pr_analysis_completed_event_publish_failed",
                github_pr_analysis_id=payload.github_pr_analysis_id,
            )

    async def _publish_failure(self, payload, organization_id: str, *, error_category: str) -> None:
        if self._result_publisher is None:
            return
        event = build_analysis_failed_event(
            github_pr_analysis_id=payload.github_pr_analysis_id,
            project_id=payload.project_id,
            organization_id=organization_id,
            github_repository_id=payload.github_repository_id,
            pull_request_number=payload.pull_request_number,
            head_sha=payload.head_sha,
            error_category=error_category,
            retry_count=0,
            correlation_id=payload.github_pr_analysis_id,
        )
        try:
            await self._result_publisher.publish(event)
        except TransientEventProcessingError:
            logger.warning(
                "github_pr_analysis_failed_event_publish_failed",
                github_pr_analysis_id=payload.github_pr_analysis_id,
            )


__all__ = ["AnalysisRequestHandler"]
