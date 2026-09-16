"""Trajectory recording HTTP API — integration tests (real Postgres via
the `client` + `session` fixtures)."""

import uuid

from app.models import Organization, Project


async def _make_project(session, *, org_slug="acme", project_slug="payments") -> Project:
    org = Organization(name=org_slug.title(), slug=org_slug)
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
    session.add(project)
    await session.flush()
    await session.commit()
    return project


async def test_start_trajectory_returns_201(client, session):
    project = await _make_project(session)
    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories",
        json={"external_run_id": "run-1", "environment": "production"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "running"
    assert body["external_run_id"] == "run-1"
    assert body["event_count"] == 0


async def test_start_trajectory_retry_same_external_run_id_returns_same_trajectory(client, session):
    project = await _make_project(session)
    payload = {"external_run_id": "run-1", "environment": "production"}
    first = await client.post(f"/api/v1/projects/{project.id}/trajectories", json=payload)
    second = await client.post(f"/api/v1/projects/{project.id}/trajectories", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_start_trajectory_conflicting_retry_returns_409(client, session):
    project = await _make_project(session)
    await client.post(
        f"/api/v1/projects/{project.id}/trajectories",
        json={"external_run_id": "run-1", "environment": "production"},
    )
    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories",
        json={"external_run_id": "run-1", "environment": "staging"},
    )
    assert response.status_code == 409


async def test_append_valid_event_returns_201(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
        json={"event_type": "run_started", "input": {"note": "start"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["sequence_number"] == 1
    assert body["event_type"] == "run_started"


async def test_append_invalid_event_returns_422(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
        json={"event_type": "tool_call", "input": {"arguments": {}}},
    )
    assert response.status_code == 422


async def test_append_reserved_event_type_returns_422(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
        json={"event_type": "run_completed"},
    )
    assert response.status_code == 422


async def test_retrieve_ordered_events(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    for event_type in ("run_started", "agent_started", "agent_completed"):
        response = await client.post(
            f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
            json={"event_type": event_type},
        )
        assert response.status_code == 201

    response = await client.get(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [e["sequence_number"] for e in body["items"]] == [1, 2, 3]
    assert [e["event_type"] for e in body["items"]] == [
        "run_started",
        "agent_started",
        "agent_completed",
    ]


async def test_complete_trajectory_returns_200(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/complete"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["duration_seconds"] is not None


async def test_fail_trajectory_returns_200(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/fail",
        json={"error": "downstream timeout"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "downstream timeout"


async def test_append_after_completion_returns_409(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]
    await client.post(f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/complete")

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
        json={"event_type": "run_started"},
    )
    assert response.status_code == 409


async def test_invalid_transition_returns_409(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]
    await client.post(f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/complete")

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/complete"
    )
    assert response.status_code == 409


async def test_missing_trajectory_returns_404(client, session):
    project = await _make_project(session)
    response = await client.get(f"/api/v1/projects/{project.id}/trajectories/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_cross_project_isolation(client, session):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    start = await client.post(f"/api/v1/projects/{project_a.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    response = await client.get(f"/api/v1/projects/{project_b.id}/trajectories/{trajectory_id}")
    assert response.status_code == 404


async def test_list_pagination_and_status_filter(client, session):
    project = await _make_project(session)
    for _ in range(3):
        await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    completed_start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{completed_start.json()['id']}/complete"
    )

    all_response = await client.get(
        f"/api/v1/projects/{project.id}/trajectories", params={"page": 1, "page_size": 2}
    )
    assert all_response.status_code == 200
    body = all_response.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2

    completed_response = await client.get(
        f"/api/v1/projects/{project.id}/trajectories", params={"status": "completed"}
    )
    assert completed_response.json()["total"] == 1


async def test_redaction_visible_in_retrieved_representation(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]

    create = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
        json={
            "event_type": "api_request",
            "input": {
                "customer_id": "991",
                "authorization": "Bearer very-secret-token",
                "nested": {"api_key": "secret-value"},
            },
        },
    )
    assert create.status_code == 201
    assert create.json()["input"]["authorization"] == "***REDACTED***"

    fetched = await client.get(f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events")
    stored_input = fetched.json()["items"][0]["input"]
    assert stored_input["customer_id"] == "991"
    assert stored_input["authorization"] == "***REDACTED***"
    assert stored_input["nested"]["api_key"] == "***REDACTED***"
    assert "very-secret-token" not in fetched.text
    assert "secret-value" not in fetched.text


# --- event_count regression coverage (MissingGreenlet fix) --------------
#
# These pin down that `event_count` in every `TrajectoryResponse` is
# computed with an explicit COUNT query rather than by touching the
# async-lazy `Trajectory.events` relationship. Before the fix, several of
# these paths raised `sqlalchemy.exc.MissingGreenlet` instead of the
# assertions below ever running.


async def test_event_count_reflects_appended_events(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]
    assert start.json()["event_count"] == 0

    for event_type in ("run_started", "agent_started"):
        response = await client.post(
            f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
            json={"event_type": event_type},
        )
        assert response.status_code == 201

    fetched = await client.get(f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}")
    assert fetched.status_code == 200
    assert fetched.json()["event_count"] == 2


async def test_list_trajectories_reports_correct_event_count_per_item(client, session):
    project = await _make_project(session)
    empty = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    populated = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    populated_id = populated.json()["id"]
    for event_type in ("run_started", "agent_started", "agent_completed"):
        response = await client.post(
            f"/api/v1/projects/{project.id}/trajectories/{populated_id}/events",
            json={"event_type": event_type},
        )
        assert response.status_code == 201

    listed = await client.get(
        f"/api/v1/projects/{project.id}/trajectories", params={"page_size": 100}
    )
    assert listed.status_code == 200
    by_id = {item["id"]: item["event_count"] for item in listed.json()["items"]}
    assert by_id[empty.json()["id"]] == 0
    assert by_id[populated_id] == 3


async def test_complete_trajectory_reports_correct_event_count(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]
    await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
        json={"event_type": "run_started"},
    )

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/complete"
    )
    assert response.status_code == 200
    assert response.json()["event_count"] == 1


async def test_fail_trajectory_reports_correct_event_count(client, session):
    project = await _make_project(session)
    start = await client.post(f"/api/v1/projects/{project.id}/trajectories", json={})
    trajectory_id = start.json()["id"]
    for event_type in ("run_started", "agent_started"):
        await client.post(
            f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
            json={"event_type": event_type},
        )

    response = await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/fail",
        json={"error": "downstream timeout"},
    )
    assert response.status_code == 200
    assert response.json()["event_count"] == 2


async def test_idempotent_retry_reports_existing_event_count(client, session):
    project = await _make_project(session)
    payload = {"external_run_id": "run-1", "environment": "production"}
    first = await client.post(f"/api/v1/projects/{project.id}/trajectories", json=payload)
    trajectory_id = first.json()["id"]
    await client.post(
        f"/api/v1/projects/{project.id}/trajectories/{trajectory_id}/events",
        json={"event_type": "run_started"},
    )

    retry = await client.post(f"/api/v1/projects/{project.id}/trajectories", json=payload)
    assert retry.status_code == 201
    assert retry.json()["id"] == trajectory_id
    assert retry.json()["event_count"] == 1
