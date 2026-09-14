"""Membership-mutation authorization — pure unit tests (Security Phase C
spec §16/§17/§24/§26). `app/authz/membership.py` has no SQLAlchemy/
FastAPI import, so this runs for real via `pytest --noconftest`. No
membership-mutation API exists yet, so these test the decision function
directly — see that module's docstring for the documented future route.
"""

import pytest

from app.authz.membership import authorize_role_change
from app.domain.exceptions import PermissionDenied


def test_owner_can_change_a_non_owner_membership():
    authorize_role_change(
        actor_role="owner", target_current_role="member", new_role="admin", is_last_owner=False
    )  # does not raise


def test_owner_can_demote_a_non_last_owner():
    authorize_role_change(
        actor_role="owner", target_current_role="owner", new_role="admin", is_last_owner=False
    )  # does not raise


def test_member_cannot_change_any_membership_including_self():
    with pytest.raises(PermissionDenied):
        authorize_role_change(
            actor_role="member",
            target_current_role="member",
            new_role="admin",
            is_last_owner=False,
        )


def test_admin_cannot_promote_self_to_owner():
    with pytest.raises(PermissionDenied):
        authorize_role_change(
            actor_role="admin", target_current_role="admin", new_role="owner", is_last_owner=False
        )


def test_admin_cannot_change_any_membership():
    with pytest.raises(PermissionDenied):
        authorize_role_change(
            actor_role="admin",
            target_current_role="member",
            new_role="admin",
            is_last_owner=False,
        )


def test_owner_cannot_demote_the_last_owner():
    with pytest.raises(PermissionDenied):
        authorize_role_change(
            actor_role="owner", target_current_role="owner", new_role="admin", is_last_owner=True
        )


def test_no_role_cannot_change_any_membership():
    with pytest.raises(PermissionDenied):
        authorize_role_change(
            actor_role=None, target_current_role="member", new_role="admin", is_last_owner=False
        )
