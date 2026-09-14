"""Role-to-permission matrix — pure unit tests (Security Phase C spec
§21). `app/authz/permissions.py` has no SQLAlchemy/FastAPI import, so
this runs for real via `pytest --noconftest`."""

from app.authz.permissions import ROLE_PERMISSIONS, Permission, role_has_permission

_ALL_PERMISSIONS = set(Permission)

_MEMBER_READ_ONLY = {
    Permission.PROJECT_READ,
    Permission.COMPONENT_READ,
    Permission.SCAN_READ,
    Permission.TRAJECTORY_READ,
    Permission.REPLAY_READ,
    Permission.GRAPH_READ,
}

_ENGINEERING_WRITES = {
    Permission.PROJECT_CREATE,
    Permission.PROJECT_UPDATE,
    Permission.COMPONENT_WRITE,
    Permission.SCAN_EXECUTE,
    Permission.TRAJECTORY_WRITE,
    Permission.REPLAY_EXECUTE,
    Permission.GRAPH_WRITE,
    # Security Phase E spec §17: ADMIN may read the audit trail.
    Permission.AUDIT_READ,
}

_GOVERNANCE = {Permission.MEMBERSHIP_MANAGE, Permission.ORG_MANAGE}


def test_member_has_exactly_read_permissions():
    assert ROLE_PERMISSIONS["member"] == _MEMBER_READ_ONLY


def test_member_cannot_write_or_execute():
    for permission in _ENGINEERING_WRITES | _GOVERNANCE:
        assert not role_has_permission("member", permission), permission


def test_admin_has_member_permissions_plus_engineering_writes():
    assert ROLE_PERMISSIONS["admin"] == _MEMBER_READ_ONLY | _ENGINEERING_WRITES


def test_admin_can_execute_scans_and_replays():
    assert role_has_permission("admin", Permission.SCAN_EXECUTE)
    assert role_has_permission("admin", Permission.REPLAY_EXECUTE)
    assert role_has_permission("admin", Permission.COMPONENT_WRITE)


def test_admin_cannot_manage_membership_or_org():
    assert not role_has_permission("admin", Permission.MEMBERSHIP_MANAGE)
    assert not role_has_permission("admin", Permission.ORG_MANAGE)


def test_owner_has_every_permission():
    assert ROLE_PERMISSIONS["owner"] == _ALL_PERMISSIONS


def test_owner_strictly_a_superset_of_admin_strictly_a_superset_of_member():
    member, admin, owner = (
        ROLE_PERMISSIONS["member"],
        ROLE_PERMISSIONS["admin"],
        ROLE_PERMISSIONS["owner"],
    )
    assert member < admin < owner  # strict subset: OWNER > ADMIN > MEMBER


def test_member_can_read_everything_admin_and_owner_can():
    for permission in _MEMBER_READ_ONLY:
        assert role_has_permission("member", permission)
        assert role_has_permission("admin", permission)
        assert role_has_permission("owner", permission)


def test_role_has_permission_denies_for_no_role():
    for permission in Permission:
        assert role_has_permission(None, permission) is False


def test_role_has_permission_denies_for_unknown_role_string():
    for permission in Permission:
        assert role_has_permission("superadmin", permission) is False


def test_every_permission_is_covered_by_at_least_one_role():
    covered = ROLE_PERMISSIONS["owner"]
    assert covered == _ALL_PERMISSIONS


def test_permission_matrix_full_cross_product():
    # Exhaustive: every (role, permission) pair matches the documented
    # policy exactly — not just spot checks.
    expected = {
        "member": _MEMBER_READ_ONLY,
        "admin": _MEMBER_READ_ONLY | _ENGINEERING_WRITES,
        "owner": _ALL_PERMISSIONS,
    }
    for role, granted in expected.items():
        for permission in Permission:
            assert role_has_permission(role, permission) == (permission in granted), (
                role,
                permission,
            )
