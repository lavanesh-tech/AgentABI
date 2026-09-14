"""Audit action taxonomy — pure unit tests. `app/audit/actions.py` has
no SQLAlchemy import, so this runs for real via `pytest --noconftest`.
"""

from app.audit.actions import AuditAction


def test_every_action_is_a_stable_lowercase_string_value():
    for action in AuditAction:
        assert action.value == action.value.lower()
        assert " " not in action.value


def test_expected_minimum_actions_are_present():
    values = {a.value for a in AuditAction}
    assert values >= {
        "login_success",
        "login_failure",
        "authorization_denied",
        "project_created",
        "scan_triggered",
        "replay_triggered",
        "github_webhook_processed",
        "github_webhook_rejected",
    }
