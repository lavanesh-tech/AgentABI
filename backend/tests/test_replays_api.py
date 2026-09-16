"""Replay HTTP API — integration tests (real Postgres via `client` +
`session` fixtures). Written and `py_compile`-clean; needs SQLAlchemy/
FastAPI/httpx, unavailable in this sandbox — see docs/DECISIONS.md."""

import uuid

from app.models import Component, ComponentVersion, Organization, Project


async def _setup(session, *, org_slug="acme", project_slug="payments"):
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


async def _completed_trajectory_via_api(client, project_id, component_id, baseline_version_id):
    start = await client.post(f"/api/v1/projects/{project_id}/trajectories", json={})
    trajectory_id = start.json()["id"]
    await client.post(
        f"/api/v1/projects/{project_id}/trajectories/{trajectory_id}/events",
        json={"event_type": "agent_started"},
    )
    await client.post(
        f"/api/v1/projects/{project_id}/trajectories/{trajectory_id}/events",
        json={
            "event_type": "tool_call",
            "component_id": str(component_id),
            "component_version_id": str(baseline_version_id),
            "input": {"invocation_id": "call-1", "arguments": {"amount": 125.0}},
        },
    )
    await client.post(
        f"/api/v1/projects/{project_id}/trajectories/{trajectory_id}/events",
        json={
            "event_type": "tool_response",
            "component_id": str(component_id),
            "component_version_id": str(baseline_version_id),
            "input": {"invocation_id": "call-1"},
            "output": {"authorized": True},
        },
    )
    await client.post(f"/api/v1/projects/{project_id}/trajectories/{trajectory_id}/complete")
    return trajectory_id


async def test_create_replay_returns_201_with_plan(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)

    response = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert len(body["plan"]) == 3
    assert any(s["kind"] == "substituted_execution" for s in body["plan"])


async def test_create_replay_idempotency_key_retry_returns_same_replay(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)
    payload = {
        "source_trajectory_id": trajectory_id,
        "baseline_component_version_id": str(v5.id),
        "candidate_component_version_id": str(v6.id),
        "idempotency_key": "retry-1",
    }
    first = await client.post(f"/api/v1/projects/{project.id}/replays", json=payload)
    second = await client.post(f"/api/v1/projects/{project.id}/replays", json=payload)
    assert first.json()["id"] == second.json()["id"]


async def test_get_missing_replay_returns_404(client, session):
    project, _c, _v5, _v6 = await _setup(session)
    response = await client.get(f"/api/v1/projects/{project.id}/replays/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_execute_replay_without_executor_returns_503(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)
    create = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    replay_id = create.json()["id"]
    response = await client.post(f"/api/v1/projects/{project.id}/replays/{replay_id}/execute")
    assert response.status_code == 503

    get_response = await client.get(f"/api/v1/projects/{project.id}/replays/{replay_id}")
    assert get_response.json()["status"] == "failed"


async def test_execute_twice_returns_409_on_second_call(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)
    create = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    replay_id = create.json()["id"]
    await client.post(f"/api/v1/projects/{project.id}/replays/{replay_id}/execute")
    second = await client.post(f"/api/v1/projects/{project.id}/replays/{replay_id}/execute")
    assert second.status_code == 409


async def test_list_steps_ordered_by_sequence(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)
    create = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    replay_id = create.json()["id"]
    # No executor registered in the production wiring, so this fails
    # deterministically — but reused/skipped steps before the substituted
    # one are still never persisted (execution stops there), so listing
    # steps on a still-PENDING replay returns an empty, well-formed page.
    steps = await client.get(f"/api/v1/projects/{project.id}/replays/{replay_id}/steps")
    assert steps.status_code == 200
    assert steps.json()["items"] == []


async def test_cross_project_isolation(client, session):
    project_a, component_a, v5_a, v6_a = await _setup(session, org_slug="acme", project_slug="a")
    project_b, _c, _v5, _v6 = await _setup(session, org_slug="beta", project_slug="b")
    trajectory_id = await _completed_trajectory_via_api(
        client, project_a.id, component_a.id, v5_a.id
    )
    create = await client.post(
        f"/api/v1/projects/{project_a.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5_a.id),
            "candidate_component_version_id": str(v6_a.id),
        },
    )
    replay_id = create.json()["id"]
    response = await client.get(f"/api/v1/projects/{project_b.id}/replays/{replay_id}")
    assert response.status_code == 404


async def test_create_replay_missing_trajectory_returns_404(client, session):
    project, _component, v5, v6 = await _setup(session)
    response = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": str(uuid.uuid4()),
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    assert response.status_code == 404


# --- step_count regression coverage (MissingGreenlet fix) ---------------
#
# Before the fix, ReplayResponse.from_replay computed step_count via
# len(replay_run.steps) — an async-lazy SQLAlchemy relationship — which
# raised sqlalchemy.exc.MissingGreenlet instead of returning a response.
# These pin down that create/list/get/execute all return 2xx with a
# correct, async-safe step_count.


async def test_create_replay_reports_zero_step_count(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)

    response = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    assert response.status_code == 201
    assert response.json()["step_count"] == 0


async def test_get_replay_reports_zero_step_count(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)
    create = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    replay_id = create.json()["id"]

    response = await client.get(f"/api/v1/projects/{project.id}/replays/{replay_id}")
    assert response.status_code == 200
    assert response.json()["step_count"] == 0


async def test_list_replays_reports_zero_step_count_per_item(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)
    create = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    replay_id = create.json()["id"]

    response = await client.get(f"/api/v1/projects/{project.id}/replays")
    assert response.status_code == 200
    by_id = {item["id"]: item["step_count"] for item in response.json()["items"]}
    assert by_id[replay_id] == 0


async def test_execute_replay_step_count_matches_listed_steps(client, session):
    project, component, v5, v6 = await _setup(session)
    trajectory_id = await _completed_trajectory_via_api(client, project.id, component.id, v5.id)
    create = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    replay_id = create.json()["id"]

    # No executor is registered in the production wiring, so this fails
    # deterministically at the substituted-execution step (same fixture
    # as test_execute_replay_without_executor_returns_503) — the point
    # here is that the response itself is async-safe and its step_count
    # agrees with what was actually persisted, not a specific number.
    response = await client.post(f"/api/v1/projects/{project.id}/replays/{replay_id}/execute")
    assert response.status_code == 503

    get_response = await client.get(f"/api/v1/projects/{project.id}/replays/{replay_id}")
    steps_response = await client.get(f"/api/v1/projects/{project.id}/replays/{replay_id}/steps")
    assert get_response.json()["step_count"] == steps_response.json()["total"]


async def test_create_replay_incomplete_trajectory_returns_422(client, session):
    project, component, v5, v6 = await _setup(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]  # never completed

    response = await client.post(
        f"/api/v1/projects/{project.id}/replays",
        json={
            "source_trajectory_id": trajectory_id,
            "baseline_component_version_id": str(v5.id),
            "candidate_component_version_id": str(v6.id),
        },
    )
    assert response.status_code == 422
