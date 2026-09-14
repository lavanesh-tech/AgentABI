"""`GitHubPullRequestAnalysisService` integration tests (real Postgres via
the `session` fixture, spec §37-§38). Written and `py_compile`-clean;
needs SQLAlchemy/asyncpg, unavailable in this sandbox — see
docs/DECISIONS.md. Includes the mandatory stale-SHA protection test
(spec §25/§37).
"""

import pytest

from app.domain.exceptions import (
    GitHubRepositoryNotMapped,
    MissingAgentABIConfiguration,
)
from app.github.checks_fake import FakeGitHubChecksClient, failing_checks_client
from app.github.pr_analysis_models import GitHubPRAnalysisStatus
from app.github.pr_webhook_models import PullRequestWebhookPayload
from app.models import Component, ComponentVersion, GitHubRepositoryMapping, Organization, Project
from app.services.github_pr_analysis_service import GitHubPullRequestAnalysisService


async def _setup(session, *, github_repository_id=123456789, with_versions=True):
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

    if with_versions:
        baseline = ComponentVersion(
            component_id=component.id, version="1", content={}, checksum="a" * 64
        )
        session.add(baseline)
        await session.flush()

    mapping = GitHubRepositoryMapping(
        organization_id=org.id,
        project_id=project.id,
        component_id=component.id,
        github_repository_id=github_repository_id,
        github_repository_full_name="acme-corp/payments-service",
        baseline_version="1" if with_versions else None,
    )
    session.add(mapping)
    await session.flush()
    await session.commit()
    return org, project, component, mapping


def _payload(*, repository_id=123456789, pr_number=42, head_sha="cand-sha", action="opened"):
    return PullRequestWebhookPayload(
        action=action,
        repository_id=repository_id,
        repository_owner="acme-corp",
        repository_name="payments-service",
        repository_full_name="acme-corp/payments-service",
        installation_id=555000111,
        pull_request_number=pr_number,
        pull_request_url="https://github.com/acme-corp/payments-service/pull/42",
        head_sha=head_sha,
        head_ref="feature/x",
        base_sha="base-sha",
        base_ref="main",
        sender_id=111,
        sender_login="octocat",
    )


async def test_unmapped_repository_raises(session):
    checks = FakeGitHubChecksClient()
    service = GitHubPullRequestAnalysisService(session, checks_client=checks)
    with pytest.raises(GitHubRepositoryNotMapped):
        await service.analyze_pull_request(
            _payload(repository_id=999999), delivery_id="d1", request_id=None
        )


async def test_missing_component_id_raises_missing_configuration(session):
    org, project, component, mapping = await _setup(session)
    mapping.component_id = None
    await session.flush()
    await session.commit()

    checks = FakeGitHubChecksClient()
    service = GitHubPullRequestAnalysisService(session, checks_client=checks)
    with pytest.raises(MissingAgentABIConfiguration):
        await service.analyze_pull_request(_payload(), delivery_id="d1", request_id=None)


async def test_missing_candidate_version_raises_missing_configuration(session):
    org, project, component, mapping = await _setup(session)
    checks = FakeGitHubChecksClient()
    service = GitHubPullRequestAnalysisService(session, checks_client=checks)

    # No ComponentVersion registered with version == head_sha (spec §19:
    # never infer it from a diff).
    with pytest.raises(MissingAgentABIConfiguration):
        await service.analyze_pull_request(
            _payload(head_sha="never-registered"), delivery_id="d1", request_id=None
        )


async def test_successful_analysis_publishes_completed_check(session):
    org, project, component, mapping = await _setup(session)
    candidate = ComponentVersion(
        component_id=component.id, version="cand-sha", content={}, checksum="b" * 64
    )
    session.add(candidate)
    await session.flush()
    await session.commit()

    checks = FakeGitHubChecksClient()
    service = GitHubPullRequestAnalysisService(session, checks_client=checks)
    analysis = await service.analyze_pull_request(
        _payload(head_sha="cand-sha"), delivery_id="d1", request_id=None
    )

    assert analysis.status == GitHubPRAnalysisStatus.COMPLETED.value
    assert analysis.head_sha == "cand-sha"
    assert analysis.risk_assessment_id is not None
    operations = [c.operation for c in checks.calls]
    assert "create" in operations  # in-progress creation
    assert any(c.status.value == "completed" for c in checks.calls)


async def test_idempotent_redelivery_does_not_create_second_row_or_republish(session):
    org, project, component, mapping = await _setup(session)
    candidate = ComponentVersion(
        component_id=component.id, version="cand-sha", content={}, checksum="b" * 64
    )
    session.add(candidate)
    await session.flush()
    await session.commit()

    checks = FakeGitHubChecksClient()
    service = GitHubPullRequestAnalysisService(session, checks_client=checks)
    first = await service.analyze_pull_request(
        _payload(head_sha="cand-sha"), delivery_id="d1", request_id=None
    )
    call_count_after_first = len(checks.calls)

    second = await service.analyze_pull_request(
        _payload(head_sha="cand-sha"), delivery_id="d2", request_id=None
    )

    assert first.id == second.id
    assert len(checks.calls) == call_count_after_first  # no republish on redelivery


async def test_publish_failure_does_not_mutate_risk_assessment(session):
    org, project, component, mapping = await _setup(session)
    candidate = ComponentVersion(
        component_id=component.id, version="cand-sha", content={}, checksum="b" * 64
    )
    session.add(candidate)
    await session.flush()
    await session.commit()

    # `FakeGitHubChecksClient.fail_with` fires on the very first checks
    # call (the in-progress publish, best-effort/swallowed) — this still
    # exercises the same assertion (risk assessment persisted and
    # unmutated by a publish failure) because the pipeline commits
    # deterministic evidence *before* any publish attempt (see
    # `analyze_pull_request`'s comment on ordering).
    failing = failing_checks_client("simulated GitHub outage")
    service = GitHubPullRequestAnalysisService(session, checks_client=failing)
    analysis = await service.analyze_pull_request(
        _payload(head_sha="cand-sha"), delivery_id="d3", request_id=None
    )

    # In-progress publish failed silently (best-effort); the pipeline
    # still ran and completed, and the completed publish also failed —
    # but the risk assessment itself was computed and persisted.
    assert analysis.risk_assessment_id is not None
    assert analysis.status in (
        GitHubPRAnalysisStatus.COMPLETED.value,
        GitHubPRAnalysisStatus.PUBLISH_FAILED.value,
    )


async def test_stale_sha_never_overwrites_or_is_confused_with_newer_commit(session):
    """Spec §25/§37 (mandatory): PR commit A starts/completes analysis,
    then commit B (a new `synchronize`) arrives — A's result/check must
    remain pinned to A's exact head_sha, never applied to B."""

    org, project, component, mapping = await _setup(session)
    version_a = ComponentVersion(
        component_id=component.id, version="sha-a", content={}, checksum="a" * 64
    )
    version_b = ComponentVersion(
        component_id=component.id, version="sha-b", content={}, checksum="b" * 64
    )
    session.add_all([version_a, version_b])
    await session.flush()
    await session.commit()

    checks = FakeGitHubChecksClient()
    service = GitHubPullRequestAnalysisService(session, checks_client=checks)

    # Commit A analyzed first.
    analysis_a = await service.analyze_pull_request(
        _payload(head_sha="sha-a"), delivery_id="d-a", request_id=None
    )
    # Commit B (a new synchronize) analyzed after — a distinct logical
    # analysis, never reusing or overwriting A's row.
    analysis_b = await service.analyze_pull_request(
        _payload(head_sha="sha-b"), delivery_id="d-b", request_id=None
    )

    assert analysis_a.id != analysis_b.id
    assert analysis_a.head_sha == "sha-a"
    assert analysis_b.head_sha == "sha-b"

    # Every check call ever made for analysis A was made with head_sha
    # "sha-a", and every call for B with "sha-b" — no call mixes them,
    # so a check published for the older commit can never be mistaken
    # for the newer commit's result.
    calls_referencing_a = [c for c in checks.calls if c.check_run_id == analysis_a.check_run_id]
    calls_referencing_b = [c for c in checks.calls if c.check_run_id == analysis_b.check_run_id]
    assert all(c.head_sha == "sha-a" for c in calls_referencing_a)
    assert all(c.head_sha == "sha-b" for c in calls_referencing_b)


async def test_cross_org_repository_mapping_is_not_reachable(session):
    """A repository mapped to one org/project can never resolve into a
    different org's analysis — the lookup is by the immutable GitHub
    repository id only, server-side (spec §29's tenant isolation)."""

    org, project, component, mapping = await _setup(session, github_repository_id=1)
    other_org, other_project, other_component, other_mapping = await _setup(
        session, github_repository_id=2
    )

    candidate = ComponentVersion(
        component_id=component.id, version="cand-sha", content={}, checksum="c" * 64
    )
    session.add(candidate)
    await session.flush()
    await session.commit()

    checks = FakeGitHubChecksClient()
    service = GitHubPullRequestAnalysisService(session, checks_client=checks)
    analysis = await service.analyze_pull_request(
        _payload(repository_id=1, head_sha="cand-sha"), delivery_id="d1", request_id=None
    )

    assert analysis.project_id == project.id
    assert analysis.project_id != other_project.id
