"""Compatibility scan HTTP API — integration tests (real Postgres via the
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

    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
    membership = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.ADMIN,
    )
    session.add_all([project, membership])
    await session.flush()
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


async def _make_tool_component(client, project, headers, *, slug="authorize-payment"):
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        headers=headers,
        json={"component_type": "tool", "name": slug.title(), "slug": slug},
    )
    assert create.status_code == 201
    component_id = create.json()["id"]

    v1 = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        headers=headers,
        json={
            "version": "1",
            "content": {
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "amount": {"type": "number"},
                        "currency": {"type": "string"},
                    },
                    "required": ["customer_id", "amount", "currency"],
                },
                "output_schema": {"type": "object", "properties": {}},
            },
        },
    )
    assert v1.status_code == 201

    v2 = await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        headers=headers,
        json={
            "version": "2",
            "content": {
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["user_id", "amount"],
                },
                "output_schema": {"type": "object", "properties": {}},
            },
        },
    )
    assert v2.status_code == 201
    return component_id


async def test_create_scan_returns_201_with_changes(client, session):
    project, headers = await _make_project(session)
    component_id = await _make_tool_component(client, project, headers)

    response = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={"component_id": component_id, "baseline_version": "1", "candidate_version": "2"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "breaking"
    assert body["summary"]["total_changes"] == 3
    assert body["summary"]["breaking_count"] == 1
    assert len(body["changes"]) == 3
    paths = {c["path"] for c in body["changes"]}
    assert "$.input_schema.properties.customer_id" in paths
    assert "$.input_schema.properties.currency" in paths
    assert "$.input_schema.properties.user_id" in paths


async def test_get_scan_returns_200(client, session):
    project, headers = await _make_project(session)
    component_id = await _make_tool_component(client, project, headers)
    create = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={"component_id": component_id, "baseline_version": "1", "candidate_version": "2"},
    )
    scan_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/projects/{project.id}/compatibility/scans/{scan_id}", headers=headers
    )
    assert response.status_code == 200
    assert response.json()["id"] == scan_id


async def test_get_scan_404_for_unknown_scan(client, session):
    project, headers = await _make_project(session)
    response = await client.get(
        f"/api/v1/projects/{project.id}/compatibility/scans/{uuid.uuid4()}", headers=headers
    )
    assert response.status_code == 404


async def test_list_scans(client, session):
    project, headers = await _make_project(session)
    component_id = await _make_tool_component(client, project, headers)
    await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={"component_id": component_id, "baseline_version": "1", "candidate_version": "2"},
    )

    response = await client.get(
        f"/api/v1/projects/{project.id}/compatibility/scans", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["component_id"] == component_id


async def test_get_scan_changes(client, session):
    project, headers = await _make_project(session)
    component_id = await _make_tool_component(client, project, headers)
    create = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={"component_id": component_id, "baseline_version": "1", "candidate_version": "2"},
    )
    scan_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/projects/{project.id}/compatibility/scans/{scan_id}/changes",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert all("classification" in c and "severity" in c for c in body)


async def test_create_scan_invalid_version_returns_404(client, session):
    project, headers = await _make_project(session)
    component_id = await _make_tool_component(client, project, headers)

    response = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={
            "component_id": component_id,
            "baseline_version": "1",
            "candidate_version": "does-not-exist",
        },
    )
    assert response.status_code == 404


async def test_create_scan_unknown_component_returns_404(client, session):
    project, headers = await _make_project(session)

    response = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={
            "component_id": str(uuid.uuid4()),
            "baseline_version": "1",
            "candidate_version": "2",
        },
    )
    assert response.status_code == 404


async def test_cross_project_scan_retrieval_returns_404(client, session):
    project_a, headers_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b, headers_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    component_id = await _make_tool_component(client, project_a, headers_a)
    create = await client.post(
        f"/api/v1/projects/{project_a.id}/compatibility/scans",
        headers=headers_a,
        json={"component_id": component_id, "baseline_version": "1", "candidate_version": "2"},
    )
    scan_id = create.json()["id"]

    response = await client.get(
        f"/api/v1/projects/{project_b.id}/compatibility/scans/{scan_id}", headers=headers_b
    )
    assert response.status_code == 404


async def test_identical_version_comparison_returns_zero_changes(client, session):
    project, headers = await _make_project(session)
    component_id = await _make_tool_component(client, project, headers)

    response = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={"component_id": component_id, "baseline_version": "1", "candidate_version": "1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "compatible"
    assert body["summary"]["total_changes"] == 0
    assert body["changes"] == []


async def test_create_scan_unsupported_component_type_returns_422(client, session):
    project, headers = await _make_project(session)
    create = await client.post(
        f"/api/v1/projects/{project.id}/components",
        headers=headers,
        json={"component_type": "provider", "name": "OpenAI", "slug": "openai"},
    )
    component_id = create.json()["id"]
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        headers=headers,
        json={"version": "1", "content": {"provider_type": "openai"}},
    )
    await client.post(
        f"/api/v1/projects/{project.id}/components/{component_id}/versions",
        headers=headers,
        json={"version": "2", "content": {"provider_type": "openai", "base_url": "https://x"}},
    )

    response = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={"component_id": component_id, "baseline_version": "1", "candidate_version": "2"},
    )
    assert response.status_code == 422


async def test_create_scan_validation_error_returns_422(client, session):
    project, headers = await _make_project(session)
    response = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={"component_id": "not-a-uuid", "baseline_version": "1", "candidate_version": "2"},
    )
    assert response.status_code == 422


async def test_create_scan_rejects_unknown_extra_field(client, session):
    project, headers = await _make_project(session)
    component_id = await _make_tool_component(client, project, headers)

    response = await client.post(
        f"/api/v1/projects/{project.id}/compatibility/scans",
        headers=headers,
        json={
            "component_id": component_id,
            "baseline_version": "1",
            "candidate_version": "2",
            "unrelated_component_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 422
