"""`AnalysisRequestHandler` tests (Phase 13 spec §37, real Postgres via
the `session` fixture). Written and `py_compile`-clean; needs SQLAlchemy/
asyncpg, unavailable in this sandbox — see docs/DECISIONS.md.
"""

import pytest

from app.events.analysis_events import build_analysis_requested_event
from app.events.envelope import EVENT_TYPE_ANALYSIS_COMPLETED, build_envelope
from app.events.errors import PermanentEventProcessingError
from app.events.fake_publisher import InMemoryEventPublisher
from app.github.checks_fake import FakeGitHubChecksClient
from app.kafka.analysis_handler import AnalysisRequestHandler
from app.models import Component, ComponentVersion, GitHubRepositoryMapping, Organization, Project
from app.services.github_pr_analysis_service import GitHubPullRequestAnalysisService


async def _setup(session):
    org = Organization(name="Acme", slug="acme")
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name="Payments", slug="payments")
    session.add(project)
    await session.flush()
    component = Component(
        organization_id=org.id,
        project_id=project.id,
        component_type="tool",
        slug="authorize-payment-tool",
        name="AuthorizePaymentTool",
    )
    session.add(component)
    await session.flush()
    baseline = ComponentVersion(
        component_id=component.id, version="1", content={}, checksum="a" * 64
    )
    candidate = ComponentVersion(
        component_id=component.id, version="cand-sha", content={}, checksum="b" * 64
    )
    session.add_all([baseline, candidate])
    await session.flush()
    mapping = GitHubRepositoryMapping(
        organization_id=org.id,
        project_id=project.id,
        component_id=component.id,
        github_repository_id=123456789,
        github_repository_full_name="acme-corp/payments-service",
        baseline_version="1",
    )
    session.add(mapping)
    await session.flush()
    await session.commit()
    return org, project, mapping


def _requested_event(*, project_id, github_pr_analysis_id, head_sha="cand-sha"):
    return build_analysis_requested_event(
        github_pr_analysis_id=str(github_pr_analysis_id),
        project_id=str(project_id),
        organization_id="org-ignored-by-handler",
        github_repository_id=123456789,
        pull_request_number=42,
        head_sha=head_sha,
        base_sha="base-sha",
        component_id=None,
        baseline_version=None,
        correlation_id="delivery-1",
    )


async def test_valid_event_processed_and_completed_event_published(session):
    org, project, mapping = await _setup(session)
    checks = FakeGitHubChecksClient()
    pr_service = GitHubPullRequestAnalysisService(session, checks_client=checks)
    from app.github.pr_webhook_models import PullRequestWebhookPayload

    payload = PullRequestWebhookPayload(
        action="opened",
        repository_id=123456789,
        repository_owner="acme-corp",
        repository_name="payments-service",
        repository_full_name="acme-corp/payments-service",
        installation_id=None,
        pull_request_number=42,
        pull_request_url="https://github.com/acme-corp/payments-service/pull/42",
        head_sha="cand-sha",
        head_ref="feature/x",
        base_sha="base-sha",
        base_ref="main",
        sender_id=1,
        sender_login="octocat",
    )
    analysis = await pr_service.start_analysis(payload, delivery_id="d1", request_id=None)

    result_publisher = InMemoryEventPublisher()
    handler = AnalysisRequestHandler(
        session, checks_client=FakeGitHubChecksClient(), result_publisher=result_publisher
    )
    event = _requested_event(project_id=project.id, github_pr_analysis_id=analysis.id)
    await handler.handle(event)

    completed = [
        p for p in result_publisher.published if p.event.event_type == EVENT_TYPE_ANALYSIS_COMPLETED
    ]
    assert len(completed) == 1
    assert completed[0].event.payload["decision"] in ("PASS", "WARN", "BLOCK")


async def test_wrong_event_type_rejected_as_permanent(session):
    handler = AnalysisRequestHandler(session, checks_client=FakeGitHubChecksClient())
    wrong_event = build_envelope(
        event_type="github.pr.analysis.completed", payload={}, correlation_id="c1"
    )
    with pytest.raises(PermanentEventProcessingError):
        await handler.handle(wrong_event)


async def test_unsupported_event_version_rejected(session):
    import dataclasses

    handler = AnalysisRequestHandler(session, checks_client=FakeGitHubChecksClient())
    event = _requested_event(
        project_id="00000000-0000-0000-0000-000000000000", github_pr_analysis_id="x"
    )
    bumped = dataclasses.replace(event, event_version=999)
    with pytest.raises(PermanentEventProcessingError):
        await handler.handle(bumped)


async def test_unknown_analysis_id_rejected_as_permanent(session):
    org, project, mapping = await _setup(session)
    handler = AnalysisRequestHandler(session, checks_client=FakeGitHubChecksClient())
    event = _requested_event(
        project_id=project.id, github_pr_analysis_id="00000000-0000-0000-0000-000000000000"
    )
    with pytest.raises(PermanentEventProcessingError):
        await handler.handle(event)


async def test_duplicate_event_remains_idempotent(session):
    org, project, mapping = await _setup(session)
    from app.github.pr_webhook_models import PullRequestWebhookPayload

    payload = PullRequestWebhookPayload(
        action="opened",
        repository_id=123456789,
        repository_owner="acme-corp",
        repository_name="payments-service",
        repository_full_name="acme-corp/payments-service",
        installation_id=None,
        pull_request_number=42,
        pull_request_url="https://github.com/acme-corp/payments-service/pull/42",
        head_sha="cand-sha",
        head_ref="feature/x",
        base_sha="base-sha",
        base_ref="main",
        sender_id=1,
        sender_login="octocat",
    )
    pr_service = GitHubPullRequestAnalysisService(session, checks_client=FakeGitHubChecksClient())
    analysis = await pr_service.start_analysis(payload, delivery_id="d1", request_id=None)

    checks = FakeGitHubChecksClient()
    handler = AnalysisRequestHandler(session, checks_client=checks)
    event = _requested_event(project_id=project.id, github_pr_analysis_id=analysis.id)

    await handler.handle(event)
    call_count_after_first = len(checks.calls)
    await handler.handle(event)  # redelivery of the identical event
    assert len(checks.calls) == call_count_after_first
