"""ReplayService — integration tests (real Postgres via `session`
fixture). Written and `py_compile`-clean; needs SQLAlchemy/asyncpg,
unavailable in this sandbox — see docs/DECISIONS.md."""

import pytest

from app.models import Component, ComponentVersion, Organization, Project
from app.replay.executor import ExecutorRegistry, FakeReplayExecutor
from app.replay.models import ExecutionOutcome, ReplayStatus, StepKind, StepStatus
from app.services.replay_service import ReplayService
from app.services.trajectory_recorder import TrajectoryRecorderService
from app.trajectory.models import EventType, TrajectoryStatus


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
    await session.commit()
    return project, component, v5, v6


async def _completed_trajectory(session, project_id):
    recorder = TrajectoryRecorderService(session)
    trajectory = await recorder.start_trajectory(project_id)
    await session.commit()
    return trajectory, recorder


async def _checkout_run(session, project, component, baseline_version):
    trajectory, recorder = await _completed_trajectory(session, project.id)
    await recorder.append_event(project.id, trajectory.id, event_type=EventType.AGENT_STARTED)
    await recorder.append_event(
        project.id, trajectory.id, event_type=EventType.MODEL_REQUEST, input={"messages": []}
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.MODEL_RESPONSE,
        output={"tool_calls": [{"name": "authorize_payment"}]},
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.TOOL_CALL,
        component_id=component.id,
        component_version_id=baseline_version.id,
        input={
            "invocation_id": "call-1",
            "arguments": {"customer_id": "customer-991", "amount": 125.0, "currency": "USD"},
        },
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.TOOL_RESPONSE,
        component_id=component.id,
        component_version_id=baseline_version.id,
        input={"invocation_id": "call-1"},
        output={"authorized": True, "authorization_id": "auth-829"},
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.STATE_WRITE,
        input={"key": "order_status", "current_value": "PAYMENT_AUTHORIZED"},
    )
    await recorder.append_event(project.id, trajectory.id, event_type=EventType.AGENT_COMPLETED)
    await recorder.complete_trajectory(project.id, trajectory.id)
    await session.commit()
    return await recorder.get_trajectory(project.id, trajectory.id)


async def test_create_replay_produces_deterministic_plan(session):
    project, component, v5, v6 = await _setup(session)
    trajectory = await _checkout_run(session, project, component, v5)

    service = ReplayService(session)
    replay = await service.create_replay(
        project.id,
        source_trajectory_id=trajectory.id,
        baseline_component_version_id=v5.id,
        candidate_component_version_id=v6.id,
    )
    await session.commit()
    assert replay.status == ReplayStatus.PENDING
    assert len(replay.plan) == 7
    substituted = [s for s in replay.plan if s["kind"] == StepKind.SUBSTITUTED_EXECUTION.value]
    assert len(substituted) == 1
    assert substituted[0]["execution_component_version_id"] == str(v6.id)


async def test_create_replay_rejects_candidate_from_a_different_component(session):
    from app.domain.exceptions import InvalidReplaySubstitution

    project, component, v5, v6 = await _setup(session)
    trajectory = await _checkout_run(session, project, component, v5)

    other_component = Component(
        organization_id=project.organization_id,
        project_id=project.id,
        component_type="tool",
        slug="unrelated-tool",
        name="UnrelatedTool",
    )
    session.add(other_component)
    await session.flush()
    unrelated_version = ComponentVersion(
        component_id=other_component.id, version="1", content={}, checksum="c" * 64
    )
    session.add(unrelated_version)
    await session.flush()
    await session.commit()

    service = ReplayService(session)
    with pytest.raises(InvalidReplaySubstitution):
        await service.create_replay(
            project.id,
            source_trajectory_id=trajectory.id,
            baseline_component_version_id=v5.id,
            candidate_component_version_id=unrelated_version.id,
        )


async def test_execute_replay_invokes_candidate_not_baseline(session):
    project, component, v5, v6 = await _setup(session)
    trajectory = await _checkout_run(session, project, component, v5)

    fake = FakeReplayExecutor(
        responses={
            (EventType.TOOL_CALL, v6.id): ExecutionOutcome(
                status="executed", output={"authorized": True, "authorization_id": "auth-999"}
            )
        }
    )
    service = ReplayService(session, executor_registry=ExecutorRegistry([fake]))
    replay = await service.create_replay(
        project.id,
        source_trajectory_id=trajectory.id,
        baseline_component_version_id=v5.id,
        candidate_component_version_id=v6.id,
    )
    await session.commit()

    executed = await service.execute_replay(project.id, replay.id)
    await session.commit()

    assert executed.status == ReplayStatus.COMPLETED
    assert len(fake.invocations) == 1
    assert fake.invocations[0]["component_version_id"] == v6.id
    assert fake.invocations[0]["input"]["arguments"]["customer_id"] == "customer-991"

    steps = await service.list_steps(project.id, replay.id)
    substituted_step = next(s for s in steps.items if s.kind == StepKind.SUBSTITUTED_EXECUTION)
    assert substituted_step.status == StepStatus.EXECUTED
    assert substituted_step.component_version_id == v6.id
    assert substituted_step.output["authorization_id"] == "auth-999"

    # Original trajectory is untouched.
    original = await TrajectoryRecorderService(session).get_trajectory(project.id, trajectory.id)
    assert original.status == TrajectoryStatus.COMPLETED
    tool_response = next(e for e in original.events if e.event_type == EventType.TOOL_RESPONSE)
    assert tool_response.output["authorization_id"] == "auth-829"
    assert tool_response.component_version_id == v5.id


async def test_execute_replay_without_executor_raises_unavailable(session):
    from app.domain.exceptions import ReplayExecutorUnavailable

    project, component, v5, v6 = await _setup(session)
    trajectory = await _checkout_run(session, project, component, v5)
    service = ReplayService(session)
    replay = await service.create_replay(
        project.id,
        source_trajectory_id=trajectory.id,
        baseline_component_version_id=v5.id,
        candidate_component_version_id=v6.id,
    )
    await session.commit()

    with pytest.raises(ReplayExecutorUnavailable):
        await service.execute_replay(project.id, replay.id)
    await session.commit()
    refreshed = await service.get_replay(project.id, replay.id)
    assert refreshed.status == ReplayStatus.FAILED


async def test_execute_replay_on_terminal_replay_raises_invalid_transition(session):
    from app.domain.exceptions import InvalidReplayTransition

    project, component, v5, v6 = await _setup(session)
    trajectory = await _checkout_run(session, project, component, v5)
    fake = FakeReplayExecutor()
    service = ReplayService(session, executor_registry=ExecutorRegistry([fake]))
    replay = await service.create_replay(
        project.id,
        source_trajectory_id=trajectory.id,
        baseline_component_version_id=v5.id,
        candidate_component_version_id=v6.id,
    )
    await session.commit()
    await service.execute_replay(project.id, replay.id)
    await session.commit()

    with pytest.raises(InvalidReplayTransition):
        await service.execute_replay(project.id, replay.id)


async def test_create_replay_idempotency_key_returns_existing_on_exact_retry(session):
    project, component, v5, v6 = await _setup(session)
    trajectory = await _checkout_run(session, project, component, v5)
    service = ReplayService(session)
    first = await service.create_replay(
        project.id,
        source_trajectory_id=trajectory.id,
        baseline_component_version_id=v5.id,
        candidate_component_version_id=v6.id,
        idempotency_key="retry-1",
    )
    await session.commit()
    second = await service.create_replay(
        project.id,
        source_trajectory_id=trajectory.id,
        baseline_component_version_id=v5.id,
        candidate_component_version_id=v6.id,
        idempotency_key="retry-1",
    )
    assert first.id == second.id


async def test_create_replay_requires_completed_trajectory(session):
    from app.domain.exceptions import InvalidReplaySubstitution

    project, component, v5, v6 = await _setup(session)
    trajectory, _recorder = await _completed_trajectory(session, project.id)  # still RUNNING
    service = ReplayService(session)
    with pytest.raises(InvalidReplaySubstitution):
        await service.create_replay(
            project.id,
            source_trajectory_id=trajectory.id,
            baseline_component_version_id=v5.id,
            candidate_component_version_id=v6.id,
        )


async def test_cross_project_isolation_for_replay_creation(session):
    from app.domain.exceptions import TrajectoryNotFound

    project_a, component_a, v5_a, v6_a = await _setup(session, org_slug="acme", project_slug="a")
    project_b, _c, _v5, _v6 = await _setup(session, org_slug="beta", project_slug="b")
    trajectory = await _checkout_run(session, project_a, component_a, v5_a)

    service = ReplayService(session)
    with pytest.raises(TrajectoryNotFound):
        await service.create_replay(
            project_b.id,
            source_trajectory_id=trajectory.id,
            baseline_component_version_id=v5_a.id,
            candidate_component_version_id=v6_a.id,
        )
