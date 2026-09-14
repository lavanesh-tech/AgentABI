"""Pure unit tests for `app/events/analysis_events.py` (Phase 13 spec
§4/§14/§24/§27/§28/§35/§43). No SQLAlchemy import there, so this runs for
real via `pytest --noconftest`.
"""

import dataclasses

import pytest

from app.events.analysis_events import (
    AnalysisRequestedPayload,
    build_analysis_completed_event,
    build_analysis_failed_event,
    build_analysis_requested_event,
    parse_analysis_requested_payload,
    partition_key,
)
from app.events.envelope import (
    EVENT_TYPE_ANALYSIS_COMPLETED,
    EVENT_TYPE_ANALYSIS_FAILED,
    EVENT_TYPE_ANALYSIS_REQUESTED,
    deserialize_envelope,
    serialize_envelope,
)
from app.events.errors import MalformedEventPayload

# Fields that must never appear anywhere in the event schema (spec §43).
_FORBIDDEN_SUBSTRINGS = (
    "token",
    "secret",
    "authorization",
    "api_key",
    "apikey",
    "password",
    "jwt",
)


def _requested_kwargs(**overrides):
    kwargs = {
        "github_pr_analysis_id": "analysis-1",
        "project_id": "project-1",
        "organization_id": "org-1",
        "github_repository_id": 123456789,
        "pull_request_number": 42,
        "head_sha": "sha-a",
        "base_sha": "base-sha",
        "component_id": "component-1",
        "baseline_version": "1",
        "correlation_id": "delivery-1",
    }
    kwargs.update(overrides)
    return kwargs


def test_partition_key_is_stable_and_scoped_to_repo_and_pr():
    assert partition_key(123456789, 42) == "123456789:42"
    assert partition_key(123456789, 42) == partition_key(123456789, 42)
    assert partition_key(123456789, 42) != partition_key(123456789, 43)
    assert partition_key(123456789, 42) != partition_key(1, 42)


def test_build_analysis_requested_event_type_and_version():
    event = build_analysis_requested_event(**_requested_kwargs())
    assert event.event_type == EVENT_TYPE_ANALYSIS_REQUESTED
    assert event.event_version == 1


def test_build_analysis_requested_event_sets_partition_key_metadata():
    event = build_analysis_requested_event(**_requested_kwargs())
    assert event.metadata["partition_key"] == "123456789:42"


def test_build_analysis_requested_event_payload_fields():
    event = build_analysis_requested_event(**_requested_kwargs())
    assert event.payload == {
        "github_pr_analysis_id": "analysis-1",
        "project_id": "project-1",
        "github_repository_id": 123456789,
        "pull_request_number": 42,
        "head_sha": "sha-a",
        "base_sha": "base-sha",
        "component_id": "component-1",
        "baseline_version": "1",
    }


def test_build_analysis_completed_event_omits_raw_evidence():
    event = build_analysis_completed_event(
        github_pr_analysis_id="analysis-1",
        project_id="project-1",
        organization_id="org-1",
        github_repository_id=123456789,
        pull_request_number=42,
        head_sha="sha-a",
        risk_assessment_id="risk-1",
        decision="PASS",
        score=5,
        correlation_id="delivery-1",
    )
    assert event.event_type == EVENT_TYPE_ANALYSIS_COMPLETED
    assert event.payload["decision"] == "PASS"
    assert event.payload["score"] == 5
    # Only an identifier, never the full evidence blob (spec §27/§45).
    assert "rule_results" not in event.payload
    assert "compatibility_summary" not in event.payload


def test_build_analysis_failed_event_carries_safe_category_only():
    event = build_analysis_failed_event(
        github_pr_analysis_id="analysis-1",
        project_id="project-1",
        organization_id="org-1",
        github_repository_id=123456789,
        pull_request_number=42,
        head_sha="sha-a",
        error_category="missing_configuration",
        retry_count=2,
        correlation_id="delivery-1",
    )
    assert event.event_type == EVENT_TYPE_ANALYSIS_FAILED
    assert event.payload["error_category"] == "missing_configuration"
    assert event.payload["retry_count"] == 2
    # Never a raw exception message/stack trace (spec §28).
    assert "stack_trace" not in event.payload
    assert "exception" not in event.payload


def test_parse_analysis_requested_payload_round_trips():
    event = build_analysis_requested_event(**_requested_kwargs())
    restored_event = deserialize_envelope(serialize_envelope(event))
    payload = parse_analysis_requested_payload(restored_event)
    assert payload == AnalysisRequestedPayload(
        github_pr_analysis_id="analysis-1",
        project_id="project-1",
        github_repository_id=123456789,
        pull_request_number=42,
        head_sha="sha-a",
        base_sha="base-sha",
        component_id="component-1",
        baseline_version="1",
    )


def test_parse_analysis_requested_payload_missing_field_raises():
    event = build_analysis_requested_event(**_requested_kwargs())
    trimmed_payload = dict(event.payload)
    del trimmed_payload["head_sha"]
    broken = dataclasses.replace(event, payload=trimmed_payload)
    with pytest.raises(MalformedEventPayload):
        parse_analysis_requested_payload(broken)


def test_component_id_and_baseline_version_optional():
    event = build_analysis_requested_event(
        **_requested_kwargs(component_id=None, baseline_version=None)
    )
    payload = parse_analysis_requested_payload(event)
    assert payload.component_id is None
    assert payload.baseline_version is None


@pytest.mark.parametrize(
    "builder,kwargs",
    [
        (
            build_analysis_requested_event,
            _requested_kwargs(),
        ),
        (
            build_analysis_completed_event,
            {
                "github_pr_analysis_id": "a1",
                "project_id": "p1",
                "organization_id": "o1",
                "github_repository_id": 1,
                "pull_request_number": 1,
                "head_sha": "sha",
                "risk_assessment_id": "r1",
                "decision": "PASS",
                "score": 0,
                "correlation_id": "c1",
            },
        ),
        (
            build_analysis_failed_event,
            {
                "github_pr_analysis_id": "a1",
                "project_id": "p1",
                "organization_id": "o1",
                "github_repository_id": 1,
                "pull_request_number": 1,
                "head_sha": "sha",
                "error_category": "missing_configuration",
                "retry_count": 0,
                "correlation_id": "c1",
            },
        ),
    ],
)
def test_no_secret_fields_in_any_event_schema(builder, kwargs):
    event = builder(**kwargs)
    serialized_text = serialize_envelope(event).decode().lower()
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in serialized_text


def test_analysis_requested_payload_dataclass_fields_never_carry_secrets():
    field_names = {f.name for f in dataclasses.fields(AnalysisRequestedPayload)}
    for name in field_names:
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in name.lower()
