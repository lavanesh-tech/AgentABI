"""Component Registry HTTP API — integration tests (real Postgres via the
`client` + `session` fixtures)."""

import uuid

from app.auth.jwt import encode_token
from app.core.config import get_settings
from app.models import (
    Organization,
    OrganizationMember,
    OrganizationRole,
    Project,
    User,
)


async def _make_project(session, *, org_slug="acme", project_slug="payments"):
    org = Organization(name=org_slug.title(), slug=org_slug)
    user = User(
        email=f"{org_slug}-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Test Admin",
        is_active=True,
    )
    session.add_all([org, user])
    await session.flush()

    project = Project(
        organization_id=org.id,
        name=project_slug.title(),
        slug=project_slug,
    )
    membership = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.ADMIN,
    )
    session.add_all([project, membership])
    await session.commit()

    settings = get_settings()
    token = encode_token(
        subject=str(user.id),
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_in_seconds=3600,
        organization_id=str(org.id),
    )
    return project, {"Authorization": f"Bearer {token}"}


async def test_create_and_get_component(client, session):
    project, headers = await _make_project(session)

    response = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    component_id = body["id"]
    assert body["component_type"] == "prompt"
    assert body["status"] == "active"

    get_response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}", headers=headers
    )
    assert get_response.status_code == 200
    assert get_response.json()["slug"] == "greeting"


async def test_create_component_duplicate_returns_409(client, session):
    project, headers = await _make_project(session)
    payload = {"component_type": "prompt", "name": "Greeting", "slug": "greeting"}
    first = await client.post(
        f"/api/v1/projects/{project.id}/components", json=payload, headers=headers
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/projects/{project.id}/components", json=payload, headers=headers
    )
    assert second.status_code == 409


async def test_get_component_404_for_unknown_id(client, session):
    project, headers = await _make_project(session)
    response = await client.get(
        f"/api/v1/projects/{project.id}/components/{uuid.uuid4()}", headers=headers
    )
    assert response.status_code == 404


async def test_get_component_404_for_unknown_project(client, session):
    _, headers = await _make_project(session)
    response = await client.get(
        f"/api/v1/projects/{uuid.uuid4()}/components/{uuid.uuid4()}",
        headers=headers,
    )
    assert response.status_code == 404


async def test_create_component_validation_error_returns_422(client, session):
    project, headers = await _make_project(session)
    response = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "", "slug": "Bad Slug!"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_create_component_invalid_version_content_returns_422(client, session):
    project, headers = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
        headers=headers,
    )
    component_id = create.json()["id"]

    response = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "1", "content": {"not_the_right_field": "x"}},
        headers=headers,
    )
    assert response.status_code == 422


async def test_create_and_list_versions_with_pagination(client, session):
    project, headers = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
        headers=headers,
    )
    component_id = create.json()["id"]

    for i in range(1, 4):
        response = await client.post(
            f"/api/v1/projects/{project.id}/components/{component_id}/versions",
            json={"version": str(i), "content": {"template": f"v{i}"}},
            headers=headers,
        )
        assert response.status_code == 201

    list_response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        params={"page": 1, "page_size": 2},
        headers=headers,
    )
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    # newest first (ordered by sequence desc)
    assert body["items"][0]["version"] == "3"


async def test_get_latest_version(client, session):
    project, headers = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
        headers=headers,
    )
    component_id = create.json()["id"]
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "1", "content": {"template": "v1"}},
        headers=headers,
    )
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "v18", "content": {"template": "v2"}},
        headers=headers,
    )

    response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions/latest",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["version"] == "v18"


async def test_get_specific_version(client, session):
    project, headers = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
        headers=headers,
    )
    component_id = create.json()["id"]
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json={"version": "1", "content": {"template": "v1"}},
        headers=headers,
    )

    response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions/1",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["content"]["template"] == "v1"


async def test_get_missing_version_returns_404(client, session):
    project, headers = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
        headers=headers,
    )
    component_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions/nope",
        headers=headers,
    )
    assert response.status_code == 404


async def test_create_duplicate_version_returns_409(client, session):
    project, headers = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "Greeting", "slug": "greeting"},
        headers=headers,
    )
    component_id = create.json()["id"]
    payload = {"version": "1", "content": {"template": "v1"}}
    first = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json=payload,
        headers=headers,
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        json=payload,
        headers=headers,
    )
    assert second.status_code == 409


async def test_list_components_pagination_and_type_filter(client, session):
    project, headers = await _make_project(session)
    await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "prompt", "name": "P1", "slug": "p1"},
        headers=headers,
    )
    await client.post(
        f"/api/v1/projects/{project.id}/components",
        json={"component_type": "tool", "name": "T1", "slug": "t1"},
        headers=headers,
    )

    filtered = await client.get(
        f"/api/v1/projects/{project.id}/components",
        params={"component_type": "tool"},
        headers=headers,
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["component_type"] == "tool"


async def test_cross_project_isolation_in_api(client, session):
    project_a, headers_a = await _make_project(session, org_slug="acme", project_slug="payments")
    project_b, headers_b = await _make_project(session, org_slug="globex", project_slug="billing")

    create = await client.post(
        f"/api/v1/projects/{project_a.id}/components",
        json={"component_type": "prompt", "name": "A", "slug": "greeting"},
        headers=headers_a,
    )
    component_id = create.json()["id"]

    cross_response = await client.get(
        f"/api/v1/projects/{project_b.id}/components/{component_id}", headers=headers_b
    )
    assert cross_response.status_code == 404

    list_response = await client.get(
        f"/api/v1/projects/{project_b.id}/components", headers=headers_b
    )
    assert list_response.json()["total"] == 0
