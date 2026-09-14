"""`DifferentialService` integration tests (real Postgres via `session`
fixture, spec §29). Written and `py_compile`-clean; needs SQLAlchemy/
asyncpg, unavailable in this sandbox — see docs/DECISIONS.md.
"""

import uuid

import pytest

from app.domain.exceptions import (
    DifferentialReportNotFound,
    ReplayNotFound,
    ReplayNotReadyForDifferential,
)
from app.models import Component, ComponentVersion, Organization, Project
from app.models.replay_run import ReplayRun
from app.models.replay_step import ReplayStep
from app.replay.models import ReplayStatus, StepKind, StepStatus
from app.services.differential_service import DifferentialService


async def _setup(session, org_slug="acme", project_slug="payments"):
    org = Organization(name=org_slug.title(), slug=org_slug)
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
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

    v5 = ComponentVersion(component_id=component.id, version="5", content={}, checksum="a" * 64)
    v6 = ComponentVersion(component_id=component.id, version="6", content={}, checksum="b" * 64)
    session.add_all([v5, v6])
    await session.flush()

    trajectory_id = uuid.uuid4()  # not FK-validated here; only replay_runs.source_trajectory_id
    # points at a real trajectories row in production — this helper
    # skips full trajectory recording (already covered by
    # test_replay_service.py) to keep differential setup focused.
    return org, project, component, v5, v6, trajectory_id


async def _replay_run(
    session, org, project, component, baseline_version, candidate_version, status, steps
):
    run = ReplayRun(
        organization_id=org.id,
        project_id=project.id,
        source_trajectory_id=uuid.uuid4(),
        component_id=component.id,
        baseline_component_version_id=baseline_version.id,
        candidate_component_version_id=candidate_version.id,
        status=status,
        plan=[],
    )
    session.add(run)
    await session.flush()
    for step in steps:
        session.add(ReplayStep(replay_run_id=run.id, **step))
    await session.flush()
    await session.commit()
    return run


def _step(seq, event_id, **overrides):
    base = {
        "sequence_number": seq,
        "source_event_id": event_id,
        "kind": StepKind.REUSED_EVIDENCE,
        "status": StepStatus.REUSED,
        "component_id": None,
        "component_version_id": None,
        "input": None,
        "output": {"seq": seq},
        "error": None,
        "duration_ms": None,
    }
    base.update(overrides)
    return base


async def test_same_project_comparison_accepted(session):
    org, project, component, v5, v6, _ = await _setup(session)
    event = uuid.uuid4()
    baseline = await _replay_run(
        session, org, project, component, v5, v5, ReplayStatus.COMPLETED, [_step(0, event)]
    )
    candidate = await _replay_run(
        session, org, project, component, v5, v6, ReplayStatus.COMPLETED, [_step(0, event)]
    )

    service = DifferentialService(session)
    record = await service.run_analysis(
        project.id, baseline_replay_id=baseline.id, candidate_replay_id=candidate.id
    )

    assert record.project_id == project.id
    assert len(record.changes) == record.matched_steps + record.added_steps + record.removed_steps


async def test_cross_project_replay_id_rejected(session):
    org, project, component, v5, v6, _ = await _setup(session)
    baseline = await _replay_run(
        session, org, project, component, v5, v5, ReplayStatus.COMPLETED, [_step(0, uuid.uuid4())]
    )
    other_project_id = uuid.uuid4()

    service = DifferentialService(session)
    with pytest.raises(ReplayNotFound):
        await service.run_analysis(
            other_project_id, baseline_replay_id=baseline.id, candidate_replay_id=baseline.id
        )


async def test_non_completed_replay_rejected(session):
    org, project, component, v5, v6, _ = await _setup(session)
    pending = await _replay_run(session, org, project, component, v5, v6, ReplayStatus.PENDING, [])

    service = DifferentialService(session)
    with pytest.raises(ReplayNotReadyForDifferential):
        await service.run_analysis(
            project.id, baseline_replay_id=pending.id, candidate_replay_id=pending.id
        )


async def test_idempotent_retry_returns_same_report(session):
    org, project, component, v5, v6, _ = await _setup(session)
    event = uuid.uuid4()
    baseline = await _replay_run(
        session, org, project, component, v5, v5, ReplayStatus.COMPLETED, [_step(0, event)]
    )
    candidate = await _replay_run(
        session, org, project, component, v5, v6, ReplayStatus.COMPLETED, [_step(0, event)]
    )

    service = DifferentialService(session)
    first = await service.run_analysis(
        project.id, baseline_replay_id=baseline.id, candidate_replay_id=candidate.id
    )
    second = await service.run_analysis(
        project.id, baseline_replay_id=baseline.id, candidate_replay_id=candidate.id
    )
    assert first.id == second.id


async def test_get_report_not_found_raises(session):
    org, project, component, v5, v6, _ = await _setup(session)
    service = DifferentialService(session)
    with pytest.raises(DifferentialReportNotFound):
        await service.get_report(project.id, uuid.uuid4())


async def test_analyzer_cannot_mutate_replay_evidence(session):
    org, project, component, v5, v6, _ = await _setup(session)
    event = uuid.uuid4()
    baseline = await _replay_run(
        session, org, project, component, v5, v5, ReplayStatus.COMPLETED, [_step(0, event)]
    )
    candidate = await _replay_run(
        session, org, project, component, v5, v6, ReplayStatus.COMPLETED, [_step(0, event)]
    )
    service = DifferentialService(session)

    before = await service._replays.get_by_id(project.id, baseline.id)  # noqa: SLF001
    before_snapshot = [(s.id, s.output, s.status) for s in before.steps]

    await service.run_analysis(
        project.id, baseline_replay_id=baseline.id, candidate_replay_id=candidate.id
    )

    after = await service._replays.get_by_id(project.id, baseline.id)  # noqa: SLF001
    after_snapshot = [(s.id, s.output, s.status) for s in after.steps]
    assert before_snapshot == after_snapshot
