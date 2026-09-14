"""Tests for `InMemoryEventPublisher` (Phase 13 spec §8/§34/§36). Written
and `py_compile`-clean; needs `pytest-asyncio`, not installed in this
sandbox (same limitation as every other async test in this repo — see
`tests/test_github_checks_client_fake.py`).
"""

import pytest

from app.events.analysis_events import build_analysis_requested_event
from app.events.envelope import deserialize_envelope
from app.events.fake_publisher import InMemoryEventPublisher


def _event(head_sha="sha-a", pr_number=42):
    return build_analysis_requested_event(
        github_pr_analysis_id="analysis-1",
        project_id="project-1",
        organization_id="org-1",
        github_repository_id=123456789,
        pull_request_number=pr_number,
        head_sha=head_sha,
        base_sha="base-sha",
        component_id="component-1",
        baseline_version="1",
        correlation_id="delivery-1",
    )


@pytest.mark.asyncio
async def test_publish_records_correct_topic():
    publisher = InMemoryEventPublisher()
    await publisher.publish(_event())
    assert publisher.published[0].topic == "agentabi.analysis.requests"


@pytest.mark.asyncio
async def test_publish_records_partition_key():
    publisher = InMemoryEventPublisher()
    await publisher.publish(_event())
    assert publisher.published[0].key == "123456789:42"


@pytest.mark.asyncio
async def test_publish_records_exact_serialized_bytes():
    publisher = InMemoryEventPublisher()
    event = _event()
    await publisher.publish(event)
    restored = deserialize_envelope(publisher.published[0].serialized)
    assert restored == event


@pytest.mark.asyncio
async def test_publish_preserves_ordering():
    publisher = InMemoryEventPublisher()
    await publisher.publish(_event(head_sha="sha-a"))
    await publisher.publish(_event(head_sha="sha-b"))
    assert [p.event.payload["head_sha"] for p in publisher.published] == ["sha-a", "sha-b"]


@pytest.mark.asyncio
async def test_publish_can_simulate_a_single_failure():
    publisher = InMemoryEventPublisher(fail_with=RuntimeError("simulated"))
    with pytest.raises(RuntimeError):
        await publisher.publish(_event())
    assert publisher.published == []
    await publisher.publish(_event())  # subsequent call succeeds
    assert len(publisher.published) == 1
