"""Organization isolation + role-matrix — API integration tests (real
Postgres + HTTP, Security Phase C spec §22/§23/§24). Written and
`py_compile`-clean; needs SQLAlchemy/FastAPI/httpx, unavailable in this
sandbox — same bucket as test_auth_api.py/test_replays_api.py.

Fixture shape throughout:
    User A -> Organization A -> Project A
    User B -> Organization B -> Project B
proving User A can reach Project A but never Project B (or anything
nested under it), and vice versa — spec §22's mandatory invariant.
"""

import uuid

from app.auth.jwt import encode_token
from app.core.config import get_settings
from app.models import Organization, OrganizationMember, OrganizationRole, Project, User


async def _make_user(session, email: str) -> User:
    user = User(email=email, full_name="Test User", is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _make_org_project_member(session, user, *, role: OrganizationRole):
    org = Organization(name="Org", slug=f"org-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name="Project", slug="project")
    session.add(project)
    session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
    await session.flush()
    await session.commit()
    return org, project


def _token_for(user, *, organization_id) -> str:
    settings = get_settings()
    return encode_token(
        subject=str(user.id),
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_in_seconds=3600,
        organization_id=str(organization_id),
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _setup_two_orgs(
    session, *, role_a=OrganizationRole.MEMBER, role_b=OrganizationRole.MEMBER
):
    user_a = await _make_user(session, "a@example.com")
    org_a, project_a = await _make_org_project_member(session, user_a, role=role_a)
    user_b = await _make_user(session, "b@example.com")
    org_b, project_b = await _make_org_project_member(session, user_b, role=role_b)
    token_a = _token_for(user_a, organization_id=org_a.id)
    token_b = _token_for(user_b, organization_id=org_b.id)
    return {
        "user_a": user_a,
        "org_a": org_a,
        "project_a": project_a,
        "token_a": token_a,
        "user_b": user_b,
        "org_b": org_b,
        "project_b": project_b,
        "token_b": token_b,
    }


# --- Organization isolation (spec §22) ------------------------------------


async def test_user_a_can_access_project_a(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/projects/{ctx['project_a'].id}", headers=_auth(ctx["token_a"])
    )
    assert response.status_code == 200


async def test_user_a_cannot_access_project_b_by_guessing_its_uuid(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/projects/{ctx['project_b'].id}", headers=_auth(ctx["token_a"])
    )
    assert response.status_code == 404  # indistinguishable from not-found (ADR-042)


async def test_user_b_cannot_access_project_a(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/projects/{ctx['project_a'].id}", headers=_auth(ctx["token_b"])
    )
    assert response.status_code == 404


async def test_user_a_cannot_list_organization_b_projects(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/organizations/{ctx['org_b'].id}/projects", headers=_auth(ctx["token_a"])
    )
    assert response.status_code == 404


# --- Nested resource isolation (spec §23) ---------------------------------


async def test_user_a_cannot_list_components_of_project_b(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/projects/{ctx['project_b'].id}/components", headers=_auth(ctx["token_a"])
    )
    assert response.status_code == 404


async def test_user_a_cannot_list_scans_of_project_b(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/projects/{ctx['project_b'].id}/compatibility/scans", headers=_auth(ctx["token_a"])
    )
    assert response.status_code == 404


async def test_user_a_cannot_list_trajectories_of_project_b(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/projects/{ctx['project_b'].id}/trajectories", headers=_auth(ctx["token_a"])
    )
    assert response.status_code == 404


async def test_user_a_cannot_list_replays_of_project_b(client, session):
    ctx = await _setup_two_orgs(session)
    response = await client.get(
        f"/api/v1/projects/{ctx['project_b'].id}/replays", headers=_auth(ctx["token_a"])
    )
    assert response.status_code == 404


# --- Role matrix (spec §24) ------------------------------------------------


async def test_member_project_create_denied(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.MEMBER)
    response = await client.post(
        f"/api/v1/organizations/{ctx['org_a'].id}/projects",
        json={"name": "New", "slug": "new"},
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code == 403


async def test_admin_project_create_allowed(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.ADMIN)
    response = await client.post(
        f"/api/v1/organizations/{ctx['org_a'].id}/projects",
        json={"name": "New", "slug": "new-admin"},
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code == 201


async def test_owner_project_update_allowed(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.OWNER)
    response = await client.patch(
        f"/api/v1/projects/{ctx['project_a'].id}",
        json={"name": "Renamed"},
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code == 200


async def test_member_project_update_denied(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.MEMBER)
    response = await client.patch(
        f"/api/v1/projects/{ctx['project_a'].id}",
        json={"name": "Renamed"},
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code == 403


async def test_member_component_create_denied(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.MEMBER)
    response = await client.post(
        f"/api/v1/projects/{ctx['project_a'].id}/components",
        json={"component_type": "tool", "name": "T", "slug": "t"},
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code == 403


async def test_admin_component_create_allowed_past_authorization(client, session):
    # Proves the *authorization* layer lets ADMIN through — a 201, or a
    # later validation/business-rule status (never 401/403), confirms
    # the request reached ComponentRegistryService.
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.ADMIN)
    response = await client.post(
        f"/api/v1/projects/{ctx['project_a'].id}/components",
        json={"component_type": "tool", "name": "T", "slug": "t"},
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code not in (401, 403, 404)


async def test_member_scan_execute_denied(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.MEMBER)
    response = await client.post(
        f"/api/v1/projects/{ctx['project_a'].id}/compatibility/scans",
        json={
            "component_id": str(uuid.uuid4()),
            "baseline_version": "1",
            "candidate_version": "2",
        },
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code == 403


async def test_member_replay_execute_denied(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.MEMBER)
    response = await client.post(
        f"/api/v1/projects/{ctx['project_a'].id}/replays",
        json={
            "source_trajectory_id": str(uuid.uuid4()),
            "baseline_component_version_id": str(uuid.uuid4()),
            "candidate_component_version_id": str(uuid.uuid4()),
            "idempotency_key": "key-1",
        },
        headers=_auth(ctx["token_a"]),
    )
    assert response.status_code == 403


async def test_member_graph_read_allowed_write_denied(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.MEMBER)
    component_id = uuid.uuid4()
    read_response = await client.get(
        f"/api/v1/projects/{ctx['project_a'].id}/components/{component_id}/graph/dependencies",
        headers=_auth(ctx["token_a"]),
    )
    assert read_response.status_code != 403  # authorization allows the read through

    write_response = await client.post(
        f"/api/v1/projects/{ctx['project_a'].id}/components/{component_id}/graph/sync",
        headers=_auth(ctx["token_a"]),
    )
    assert write_response.status_code == 403


async def test_member_trajectory_write_denied_read_allowed(client, session):
    ctx = await _setup_two_orgs(session, role_a=OrganizationRole.MEMBER)
    read_response = await client.get(
        f"/api/v1/projects/{ctx['project_a'].id}/trajectories", headers=_auth(ctx["token_a"])
    )
    assert read_response.status_code == 200

    write_response = await client.post(
        f"/api/v1/projects/{ctx['project_a'].id}/trajectories",
        json={"environment": "prod"},
        headers=_auth(ctx["token_a"]),
    )
    assert write_response.status_code == 403
