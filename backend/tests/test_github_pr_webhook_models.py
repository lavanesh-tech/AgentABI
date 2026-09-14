"""Pure unit tests for `parse_pull_request_event` (Phase 12 spec §4/§6/
§36). No `httpx`/SQLAlchemy import in `app.github.pr_webhook_models`, so
this runs for real via `pytest --noconftest`.
"""

import json
from pathlib import Path

import pytest

from app.domain.exceptions import InvalidGitHubPullRequestPayload
from app.github.pr_webhook_models import SUPPORTED_ACTIONS, parse_pull_request_event

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "github_pull_request_opened.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def test_supported_actions_are_exactly_opened_synchronize_reopened():
    assert frozenset({"opened", "synchronize", "reopened"}) == SUPPORTED_ACTIONS


def test_opened_fixture_parses_successfully():
    raw = FIXTURE_PATH.read_bytes()
    payload = parse_pull_request_event(raw)
    assert payload is not None
    assert payload.action == "opened"
    assert payload.repository_id == 123456789
    assert payload.repository_full_name == "acme-corp/payments-service"
    assert payload.pull_request_number == 42
    assert payload.head_sha == "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    assert payload.head_ref == "feature/update-schema"
    assert payload.base_sha == "0f1e2d3c4b5a69788796a5b4c3d2e1f009887766"
    assert payload.base_ref == "main"
    assert payload.installation_id == 555000111
    assert payload.sender_id == 111222333
    assert payload.sender_login == "octocat"


@pytest.mark.parametrize("action", ["opened", "synchronize", "reopened"])
def test_each_supported_action_parses(action):
    data = _load_fixture()
    data["action"] = action
    payload = parse_pull_request_event(json.dumps(data).encode())
    assert payload is not None
    assert payload.action == action


@pytest.mark.parametrize("action", ["closed", "labeled", "assigned", "edited"])
def test_unsupported_action_returns_none_not_error(action):
    data = _load_fixture()
    data["action"] = action
    assert parse_pull_request_event(json.dumps(data).encode()) is None


def test_malformed_json_raises_invalid_payload_error():
    with pytest.raises(InvalidGitHubPullRequestPayload):
        parse_pull_request_event(b"{not valid json")


def test_non_object_json_raises_invalid_payload_error():
    with pytest.raises(InvalidGitHubPullRequestPayload):
        parse_pull_request_event(b"[1, 2, 3]")


def test_missing_required_field_on_supported_action_raises():
    data = _load_fixture()
    del data["pull_request"]["head"]["sha"]
    with pytest.raises(InvalidGitHubPullRequestPayload):
        parse_pull_request_event(json.dumps(data).encode())


def test_missing_repository_raises():
    data = _load_fixture()
    del data["repository"]
    with pytest.raises(InvalidGitHubPullRequestPayload):
        parse_pull_request_event(json.dumps(data).encode())


def test_installation_optional_defaults_to_none():
    data = _load_fixture()
    del data["installation"]
    payload = parse_pull_request_event(json.dumps(data).encode())
    assert payload is not None
    assert payload.installation_id is None


def test_missing_action_field_returns_none():
    data = _load_fixture()
    del data["action"]
    assert parse_pull_request_event(json.dumps(data).encode()) is None
