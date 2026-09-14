"""The Phase 13 event taxonomy for PR analysis (spec §4): exactly three
event types, typed payload dataclasses, and the builders that produce an
`EventEnvelope` for each. No SQLAlchemy import — callers (`app/services/
github_pr_analysis_service.py`, `app/kafka/analysis_handler.py`) pass
plain scalars extracted from ORM rows, never an ORM object itself, so
this module stays `pytest --noconftest`-executable and the event schema
can never accidentally grow a database-object-shaped field.
"""

from dataclasses import dataclass
from typing import Any

from app.events.envelope import (
    EVENT_TYPE_ANALYSIS_COMPLETED,
    EVENT_TYPE_ANALYSIS_FAILED,
    EVENT_TYPE_ANALYSIS_REQUESTED,
    EventEnvelope,
    build_envelope,
)
from app.events.errors import MalformedEventPayload


def partition_key(github_repository_id: int, pull_request_number: int) -> str:
    """Spec §24: all events for the same PR share one partition key, so
    Kafka's per-partition ordering guarantee applies across a PR's
    lifecycle (spec §25) — never trusted as the *sole* safety mechanism
    though; the exact-SHA check in `GitHubPullRequestAnalysisService.
    run_analysis` is what actually prevents a stale result from
    overwriting a newer one, independent of delivery order."""

    return f"{github_repository_id}:{pull_request_number}"


@dataclass(frozen=True, slots=True)
class AnalysisRequestedPayload:
    github_pr_analysis_id: str
    project_id: str
    github_repository_id: int
    pull_request_number: int
    head_sha: str
    base_sha: str
    component_id: str | None
    baseline_version: str | None


@dataclass(frozen=True, slots=True)
class AnalysisCompletedPayload:
    github_pr_analysis_id: str
    project_id: str
    github_repository_id: int
    pull_request_number: int
    head_sha: str
    risk_assessment_id: str
    decision: str
    score: int


@dataclass(frozen=True, slots=True)
class AnalysisFailedPayload:
    github_pr_analysis_id: str
    project_id: str
    github_repository_id: int
    pull_request_number: int
    head_sha: str
    error_category: str
    retry_count: int


def build_analysis_requested_event(
    *,
    github_pr_analysis_id: str,
    project_id: str,
    organization_id: str,
    github_repository_id: int,
    pull_request_number: int,
    head_sha: str,
    base_sha: str,
    component_id: str | None,
    baseline_version: str | None,
    correlation_id: str,
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "github_pr_analysis_id": github_pr_analysis_id,
        "project_id": project_id,
        "github_repository_id": github_repository_id,
        "pull_request_number": pull_request_number,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "component_id": component_id,
        "baseline_version": baseline_version,
    }
    key = partition_key(github_repository_id, pull_request_number)
    return build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED,
        payload=payload,
        correlation_id=correlation_id,
        project_id=project_id,
        organization_id=organization_id,
        metadata={"partition_key": key},
    )


def build_analysis_completed_event(
    *,
    github_pr_analysis_id: str,
    project_id: str,
    organization_id: str,
    github_repository_id: int,
    pull_request_number: int,
    head_sha: str,
    risk_assessment_id: str,
    decision: str,
    score: int,
    correlation_id: str,
) -> EventEnvelope:
    # Spec §27: only enough to identify the result, never the raw
    # deterministic evidence (rule results, compatibility diff, ...) —
    # a consumer that wants the full evidence reads it from Postgres by
    # `risk_assessment_id`.
    payload: dict[str, Any] = {
        "github_pr_analysis_id": github_pr_analysis_id,
        "project_id": project_id,
        "github_repository_id": github_repository_id,
        "pull_request_number": pull_request_number,
        "head_sha": head_sha,
        "risk_assessment_id": risk_assessment_id,
        "decision": decision,
        "score": score,
    }
    key = partition_key(github_repository_id, pull_request_number)
    return build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_COMPLETED,
        payload=payload,
        correlation_id=correlation_id,
        project_id=project_id,
        organization_id=organization_id,
        metadata={"partition_key": key},
    )


def build_analysis_failed_event(
    *,
    github_pr_analysis_id: str,
    project_id: str,
    organization_id: str,
    github_repository_id: int,
    pull_request_number: int,
    head_sha: str,
    error_category: str,
    retry_count: int,
    correlation_id: str,
) -> EventEnvelope:
    # Spec §28: a safe error *category* only — never the raw exception
    # message/stack trace, which could carry sensitive detail.
    payload: dict[str, Any] = {
        "github_pr_analysis_id": github_pr_analysis_id,
        "project_id": project_id,
        "github_repository_id": github_repository_id,
        "pull_request_number": pull_request_number,
        "head_sha": head_sha,
        "error_category": error_category,
        "retry_count": retry_count,
    }
    key = partition_key(github_repository_id, pull_request_number)
    return build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_FAILED,
        payload=payload,
        correlation_id=correlation_id,
        project_id=project_id,
        organization_id=organization_id,
        metadata={"partition_key": key},
    )


def parse_analysis_requested_payload(envelope: EventEnvelope) -> AnalysisRequestedPayload:
    p = envelope.payload
    try:
        return AnalysisRequestedPayload(
            github_pr_analysis_id=str(p["github_pr_analysis_id"]),
            project_id=str(p["project_id"]),
            github_repository_id=int(p["github_repository_id"]),
            pull_request_number=int(p["pull_request_number"]),
            head_sha=str(p["head_sha"]),
            base_sha=str(p["base_sha"]),
            component_id=(str(p["component_id"]) if p.get("component_id") is not None else None),
            baseline_version=p.get("baseline_version"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MalformedEventPayload(
            f"{envelope.event_type} payload missing/malformed field: {exc}"
        ) from exc


__all__ = [
    "AnalysisCompletedPayload",
    "AnalysisFailedPayload",
    "AnalysisRequestedPayload",
    "build_analysis_completed_event",
    "build_analysis_failed_event",
    "build_analysis_requested_event",
    "parse_analysis_requested_payload",
    "partition_key",
]
