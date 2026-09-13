"""TrajectoryRecorderService — integration tests against a real Postgres
(see the `session`/`db_engine` fixtures in conftest.py). These exercise
sequence allocation/concurrency, idempotency, tenant isolation,
immutability, and the Postgres <-> domain-model mapping that the pure
`test_trajectory_*.py` files can't cover.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.enums import ComponentType
from app.domain.exceptions import (
    ComponentNotFound,
    DuplicateTrajectoryEvent,
    InvalidTrajectoryEvent,
    InvalidTrajectoryTransition,
    TrajectoryAlreadyExists,
    TrajectoryNotFound,
    TrajectoryTerminal,
)
from app.models import Organization, Project
from app.services.component_registry import ComponentRegistryService
from app.services.trajectory_recorder import TrajectoryRecorderService
from app.trajectory.models import EventType, TrajectoryStatus


async def _make_project(session, *, org_slug="acme", project_slug="payments") -> Project:
    org = Organization(name=org_slug.title(), slug=org_slug)
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
    session.add(project)
    await session.flush()
    return project


async def _make_tool_version(registry, project, *, slug="authorize-payment"):
    component = await registry.create_component(
        project_id=project.id, component_type=ComponentType.TOOL, name=slug.title(), slug=slug
    )
    version = await registry.create_component_version(
        project_id=project.id,
        component_id=component.id,
        version="1",
        content={"input_schema": {}, "output_schema": {}},
    )
    return component, version


@pytest.fixture
def registry(session) -> ComponentRegistryService:
    return ComponentRegistryService(session)


@pytest.fixture
def recorder(session) -> TrajectoryRecorderService:
    return TrajectoryRecorderService(session)


async def test_start_trajectory_creates_running_trajectory(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id, external_run_id="run-1")
    assert trajectory.status == TrajectoryStatus.RUNNING
    assert trajectory.next_sequence == 0
    assert trajectory.completed_at is None


async def test_start_trajectory_retry_with_same_external_run_id_is_idempotent(session, recorder):
    project = await _make_project(session)
    first = await recorder.start_trajectory(
        project.id, external_run_id="run-1", environment="production"
    )
    second = await recorder.start_trajectory(
        project.id, external_run_id="run-1", environment="production"
    )
    assert first.id == second.id


async def test_start_trajectory_retry_with_conflicting_environment_is_rejected(session, recorder):
    project = await _make_project(session)
    await recorder.start_trajectory(project.id, external_run_id="run-1", environment="production")
    with pytest.raises(TrajectoryAlreadyExists):
        await recorder.start_trajectory(project.id, external_run_id="run-1", environment="staging")


async def test_start_trajectory_links_workflow_component_version(session, registry, recorder):
    project = await _make_project(session)
    component, version = await _make_tool_version(registry, project)
    trajectory = await recorder.start_trajectory(
        project.id, workflow_component_id=component.id, workflow_version_id=version.id
    )
    assert trajectory.workflow_component_id == component.id
    assert trajectory.workflow_version_id == version.id


async def test_append_event_persists_and_orders_by_sequence(session, registry, recorder):
    project = await _make_project(session)
    component, version = await _make_tool_version(registry, project)
    trajectory = await recorder.start_trajectory(project.id)

    await recorder.append_event(
        project.id, trajectory.id, event_type=EventType.RUN_STARTED, input={"note": "start"}
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.TOOL_CALL,
        component_id=component.id,
        component_version_id=version.id,
        input={"invocation_id": "call-1", "arguments": {"amount": 125.0}},
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.TOOL_RESPONSE,
        input={"invocation_id": "call-1"},
        output={"result": {"authorized": True}},
    )

    result = await recorder.list_events(project.id, trajectory.id)
    assert result.total == 3
    sequence_numbers = [e.sequence_number for e in result.items]
    assert sequence_numbers == sorted(sequence_numbers)
    assert sequence_numbers == list(range(1, 4))
    assert result.items[1].component_version_id == version.id


async def test_representative_acceptance_trajectory(session, registry, recorder):
    """The exact worked example from Phase 6 spec §28, built through the
    generic recorder — order must come back exactly 1..8."""

    project = await _make_project(session)
    agent_component, agent_version = await _make_tool_version(
        registry, project, slug="checkout-agent"
    )
    model_component, model_version = await _make_tool_version(
        registry, project, slug="checkout-model-config"
    )
    tool_component, tool_version = await _make_tool_version(
        registry, project, slug="authorize-payment-tool"
    )

    trajectory = await recorder.start_trajectory(project.id, external_run_id="checkout-run-8291")

    await recorder.append_event(project.id, trajectory.id, event_type=EventType.RUN_STARTED)
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.AGENT_STARTED,
        component_id=agent_component.id,
        component_version_id=agent_version.id,
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.MODEL_REQUEST,
        component_id=model_component.id,
        component_version_id=model_version.id,
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
        component_id=tool_component.id,
        component_version_id=tool_version.id,
        input={
            "invocation_id": "auth-call-1",
            "arguments": {"customer_id": "customer-991", "amount": 125.00, "currency": "USD"},
        },
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.TOOL_RESPONSE,
        input={"invocation_id": "auth-call-1"},
        output={"authorized": True, "authorization_id": "auth-829"},
    )
    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.STATE_WRITE,
        input={"key": "order_status", "current_value": "PAYMENT_AUTHORIZED"},
    )
    await recorder.append_event(project.id, trajectory.id, event_type=EventType.AGENT_COMPLETED)

    completed = await recorder.complete_trajectory(project.id, trajectory.id)
    assert completed.status == TrajectoryStatus.COMPLETED

    events = (await recorder.list_events(project.id, trajectory.id)).items
    assert [e.sequence_number for e in events] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [e.event_type for e in events] == [
        EventType.RUN_STARTED,
        EventType.AGENT_STARTED,
        EventType.MODEL_REQUEST,
        EventType.MODEL_RESPONSE,
        EventType.TOOL_CALL,
        EventType.TOOL_RESPONSE,
        EventType.STATE_WRITE,
        EventType.AGENT_COMPLETED,
    ]


async def test_append_event_redacts_secrets_in_persisted_evidence(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)

    event = await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.API_REQUEST,
        input={
            "customer_id": "991",
            "authorization": "Bearer very-secret-token",
            "nested": {"api_key": "secret-value"},
        },
    )

    fetched = (await recorder.list_events(project.id, trajectory.id)).items[0]
    assert fetched.input["customer_id"] == "991"
    assert fetched.input["authorization"] == "***REDACTED***"
    assert fetched.input["nested"]["api_key"] == "***REDACTED***"
    assert "very-secret-token" not in str(fetched.input)
    assert event.input["authorization"] == "***REDACTED***"


async def test_append_event_rejects_reserved_event_type(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)
    with pytest.raises(InvalidTrajectoryEvent):
        await recorder.append_event(project.id, trajectory.id, event_type=EventType.RUN_COMPLETED)


async def test_append_event_rejects_component_version_from_other_project(
    session, registry, recorder
):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    _, version_b = await _make_tool_version(registry, project_b, slug="tool-b")

    trajectory = await recorder.start_trajectory(project_a.id)
    with pytest.raises(ComponentNotFound):
        await recorder.append_event(
            project_a.id,
            trajectory.id,
            event_type=EventType.TOOL_CALL,
            component_version_id=version_b.id,
            input={"invocation_id": "call-1"},
        )


async def test_append_event_after_completion_is_rejected(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)
    await recorder.complete_trajectory(project.id, trajectory.id)
    with pytest.raises(TrajectoryTerminal):
        await recorder.append_event(project.id, trajectory.id, event_type=EventType.RUN_STARTED)


async def test_complete_after_failed_is_invalid_transition(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)
    await recorder.fail_trajectory(project.id, trajectory.id, error="boom")
    with pytest.raises(InvalidTrajectoryTransition):
        await recorder.complete_trajectory(project.id, trajectory.id)


async def test_complete_after_complete_is_invalid_transition(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)
    await recorder.complete_trajectory(project.id, trajectory.id)
    with pytest.raises(InvalidTrajectoryTransition):
        await recorder.complete_trajectory(project.id, trajectory.id)


async def test_event_idempotency_exact_retry_returns_existing(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)

    first = await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.RUN_STARTED,
        external_event_id="evt-1",
        input={"note": "start"},
    )
    second = await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.RUN_STARTED,
        external_event_id="evt-1",
        input={"note": "start"},
    )
    assert first.id == second.id
    total = (await recorder.list_events(project.id, trajectory.id)).total
    assert total == 1


async def test_event_idempotency_conflicting_retry_is_rejected(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)

    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.RUN_STARTED,
        external_event_id="evt-1",
        input={"note": "start"},
    )
    with pytest.raises(DuplicateTrajectoryEvent):
        await recorder.append_event(
            project.id,
            trajectory.id,
            event_type=EventType.RUN_STARTED,
            external_event_id="evt-1",
            input={"note": "different"},
        )


async def test_get_trajectory_404_for_unknown_id(session, recorder):
    project = await _make_project(session)
    with pytest.raises(TrajectoryNotFound):
        await recorder.get_trajectory(project.id, uuid.uuid4())


async def test_cross_project_trajectory_retrieval_is_rejected(session, recorder):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    trajectory = await recorder.start_trajectory(project_a.id)

    with pytest.raises(TrajectoryNotFound):
        await recorder.get_trajectory(project_b.id, trajectory.id)


async def test_cross_project_append_is_rejected(session, recorder):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    trajectory = await recorder.start_trajectory(project_a.id)

    with pytest.raises(TrajectoryNotFound):
        await recorder.append_event(project_b.id, trajectory.id, event_type=EventType.RUN_STARTED)


async def test_cross_project_complete_and_fail_are_rejected(session, recorder):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    trajectory = await recorder.start_trajectory(project_a.id)

    with pytest.raises(TrajectoryNotFound):
        await recorder.complete_trajectory(project_b.id, trajectory.id)
    with pytest.raises(TrajectoryNotFound):
        await recorder.fail_trajectory(project_b.id, trajectory.id)


async def test_list_trajectories_is_project_scoped(session, recorder):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    await recorder.start_trajectory(project_a.id)
    await recorder.start_trajectory(project_b.id)

    result_a = await recorder.list_trajectories(project_a.id)
    assert result_a.total == 1


async def test_external_run_id_uniqueness_is_scoped_per_project(session, recorder):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")

    a = await recorder.start_trajectory(project_a.id, external_run_id="shared-run-id")
    b = await recorder.start_trajectory(project_b.id, external_run_id="shared-run-id")
    assert a.id != b.id


async def test_jsonb_input_output_error_round_trip(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)

    await recorder.append_event(
        project.id,
        trajectory.id,
        event_type=EventType.ERROR,
        error={"message": "boom", "code": 500, "details": {"retryable": False}},
    )
    fetched = (await recorder.list_events(project.id, trajectory.id)).items[0]
    assert fetched.error == {"message": "boom", "code": 500, "details": {"retryable": False}}


async def test_occurred_at_can_differ_from_recorded_at(session, recorder):
    from datetime import UTC, datetime, timedelta

    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)
    occurred = datetime.now(UTC) - timedelta(minutes=5)

    event = await recorder.append_event(
        project.id, trajectory.id, event_type=EventType.RUN_STARTED, occurred_at=occurred
    )
    assert event.occurred_at < event.recorded_at


async def test_trajectory_event_row_is_immutable_at_the_database_level(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)
    event = await recorder.append_event(project.id, trajectory.id, event_type=EventType.RUN_STARTED)
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE trajectory_events SET content_hash = 'tampered' WHERE id = :id"),
            {"id": event.id},
        )
    await session.rollback()


async def test_deleting_project_cascades_to_trajectory_and_events(session, recorder):
    project = await _make_project(session)
    trajectory = await recorder.start_trajectory(project.id)
    await recorder.append_event(project.id, trajectory.id, event_type=EventType.RUN_STARTED)
    await session.commit()

    await session.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project.id})
    await session.commit()

    remaining_trajectories = await session.execute(
        text("SELECT count(*) FROM trajectories WHERE id = :id"), {"id": trajectory.id}
    )
    remaining_events = await session.execute(
        text("SELECT count(*) FROM trajectory_events WHERE trajectory_id = :id"),
        {"id": trajectory.id},
    )
    assert remaining_trajectories.scalar_one() == 0
    assert remaining_events.scalar_one() == 0


async def test_concurrent_appends_allocate_distinct_sequence_numbers(db_engine):
    """Real concurrency: two independent sessions append to the same
    trajectory at the same time. The atomic `next_sequence += 1
    RETURNING` allocation (Phase 6 §15) must hand out distinct sequence
    numbers with no duplicates and no gaps, never "both got 1"."""

    from app.core.database import get_session_factory

    session_factory = get_session_factory()

    async with session_factory() as setup_session:
        project = await _make_project(setup_session)
        recorder = TrajectoryRecorderService(setup_session)
        trajectory = await recorder.start_trajectory(project.id)
        await setup_session.commit()
        project_id, trajectory_id = project.id, trajectory.id

    async def _append(n: int) -> int:
        async with session_factory() as worker_session:
            worker_recorder = TrajectoryRecorderService(worker_session)
            event = await worker_recorder.append_event(
                project_id,
                trajectory_id,
                event_type=EventType.RUN_STARTED,
                input={"worker": n},
            )
            await worker_session.commit()
            return event.sequence_number

    results = await asyncio.gather(*(_append(n) for n in range(8)))
    assert sorted(results) == list(range(1, 9))
    assert len(set(results)) == 8
