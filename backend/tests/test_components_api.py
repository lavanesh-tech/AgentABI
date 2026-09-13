"""Component Registry HTTP API — integration tests (real Postgres via the
`client` + `session` fixtures)."""

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


async def test_create_and_get_component(client, session):
    project = await _make_project(session)

    response = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
    )
    assert response.status_code == 201
    body = response.json()
    component_id = body["id"]
    assert body["component_type"] == "prompt"
    assert body["status"] == "active"

    get_response = await client.get(f"/api/v1/projects/{project.id}/components/{component_id}")
    assert get_response.status_code == 200
    assert get_response.json()["slug"] == "greeting"


async def test_create_component_duplicate_returns_409(client, session):
    project = await _make_project(session)
    payload = {"component_type": "prompt", "name": "Greeting", "slug": "greeting"}
    first = await client.post(f"/api/v1/projects/{project.id}/components", json=payload)
    assert first.status_code == 201
    second = await client.post(f"/api/v1/projects/{project.id}/components", json=payload)
    assert second.status_code == 409


async def test_get_component_404_for_unknown_id(client, session):
    project = await _make_project(session)
    response = await client.get(f"/api/v1/projects/{project.id}/components/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_get_component_404_for_unknown_project(client, session):
    response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/components/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_create_component_validation_error_returns_422(client, session):
    project = await _make_project(session)
    response = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "", "slug": "Bad Slug!"},
    )
    assert response.status_code == 422


async def test_create_component_invalid_version_content_returns_422(client, session):
    project = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
    )
    component_id = create.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "1", "content": {"not_the_right_field": "x"}},
    )
    assert response.status_code == 422


async def test_create_and_list_versions_with_pagination(client, session):
    project = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
    )
    component_id = create.json()["id"]

    for i in range(1, 4):
        response = await client.post(
            f"/api/v1/projects/{project.id}/components/{component_id}/versions",
            json={"version": str(i), "content": {"template": f"v{i}"}},
        )
        assert response.status_code == 201

    list_response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        params={"page": 1, "page_size": 2},
    )
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    # newest first (ordered by sequence desc)
    assert body["items"][0]["version"] == "3"


async def test_get_latest_version(client, session):
    project = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
    )
    component_id = create.json()["id"]
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "1", "content": {"template": "v1"}},
    )
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "v18", "content": {"template": "v2"}},
    )

    response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions/latest"
    )
    assert response.status_code == 200
    assert response.json()["version"] == "v18"


async def test_get_specific_version(client, session):
    project = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
    )
    component_id = create.json()["id"]
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "1", "content": {"template": "v1"}},
    )

    response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions/1"
    )
    assert response.status_code == 200
    assert response.json()["content"]["template"] == "v1"


async def test_get_missing_version_returns_404(client, session):
    project = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
    )
    component_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions/nope"
    )
    assert response.status_code == 404


async def test_create_duplicate_version_returns_409(client, session):
    project = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
    )
    component_id = create.json()["id"]
    payload = {"version": "1", "content": {"template": "v1"}}
    first = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions", json=payload
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions", json=payload
    )
    assert second.status_code == 409


async def test_list_components_pagination_and_type_filter(client, session):
    project = await _make_project(session)
    await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "P1", "slug": "p1"},
    )
    await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "tool", "name": "T1", "slug": "t1"},
    )

    filtered = await client.get(
        f"/api/v1/projects/{project.id}/components", params={"component_type": "tool"}
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["component_type"] == "tool"


async def test_cross_project_isolation_in_api(client, session):
    project_a = await _make_project(session, org_slug="acme", project_slug="payments")
    project_b = await _make_project(session, org_slug="globex", project_slug="billing")

    create = await client.post(
        f"/api/v1/projects/{project_a.id}/components",
        json={"component_type": "prompt", "name": "A", "slug": "greeting"},
    )
    component_id = create.json()["id"]

    cross_response = await client.get(f"/api/v1/projects/{project_b.id}/components/{component_id}")
    assert cross_response.status_code == 404

    list_response = await client.get(f"/api/v1/projects/{project_b.id}/components")
    assert list_response.json()["total"] == 0
