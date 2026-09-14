"""Typed extraction of the `pull_request` GitHub webhook event (Phase 12
spec §6). Deliberately models only the fields AgentABI needs, not the
full GitHub payload — unknown extra fields are ignored, never an error.
No `httpx`/SQLAlchemy import: pure stdlib `json`/`dataclasses`, so
`parse_pull_request_event` is `pytest --noconftest`-executable.
"""

import json
from dataclasses import dataclass

from app.domain.exceptions import InvalidGitHubPullRequestPayload

# Only these actions make sense to (re)run analysis for (spec §4) — a
# PR being closed, labeled, assigned, etc. is safely ignored, never an
# error.
SUPPORTED_ACTIONS = frozenset({"opened", "synchronize", "reopened"})


@dataclass(frozen=True, slots=True)
class PullRequestWebhookPayload:
    action: str
    repository_id: int
    repository_owner: str
    repository_name: str
    repository_full_name: str
    installation_id: int | None
    pull_request_number: int
    pull_request_url: str
    head_sha: str
    head_ref: str
    base_sha: str
    base_ref: str
    sender_id: int
    sender_login: str


def parse_pull_request_event(raw_body: bytes) -> PullRequestWebhookPayload | None:
    """Returns `None` for a well-formed payload whose `action` isn't
    supported (spec §4's "ignore unsupported actions safely" — not an
    error). Raises `InvalidGitHubPullRequestPayload` for malformed JSON
    or a supported action missing a field this integration needs (spec
    §36's "invalid payload rejected safely" — safely meaning a typed
    domain error the caller can catch, never an unhandled `KeyError`/
    `TypeError` bubbling into a 500).
    """

    try:
        payload = json.loads(raw_body)
    except ValueError as exc:
        raise InvalidGitHubPullRequestPayload("body is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise InvalidGitHubPullRequestPayload("body is not a JSON object")

    action = payload.get("action")
    if not isinstance(action, str) or action not in SUPPORTED_ACTIONS:
        return None

    try:
        repository = payload["repository"]
        pull_request = payload["pull_request"]
        sender = payload["sender"]
        head = pull_request["head"]
        base = pull_request["base"]
        owner = repository["owner"]

        return PullRequestWebhookPayload(
            action=action,
            repository_id=int(repository["id"]),
            repository_owner=str(owner.get("login") or owner["login"]),
            repository_name=str(repository["name"]),
            repository_full_name=str(repository["full_name"]),
            installation_id=(
                int(payload["installation"]["id"]) if payload.get("installation") else None
            ),
            pull_request_number=int(pull_request["number"]),
            pull_request_url=str(pull_request.get("html_url", "")),
            head_sha=str(head["sha"]),
            head_ref=str(head["ref"]),
            base_sha=str(base["sha"]),
            base_ref=str(base["ref"]),
            sender_id=int(sender["id"]),
            sender_login=str(sender["login"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidGitHubPullRequestPayload(
            f"pull_request payload missing/malformed required field: {exc}"
        ) from exc
