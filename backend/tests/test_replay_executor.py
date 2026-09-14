"""Pure unit tests for `app/replay/executor.py`'s `FakeReplayExecutor`/
`ExecutorRegistry`. No database, no I/O, no external service ever
called."""

import uuid

from app.replay.executor import ExecutorRegistry, FakeReplayExecutor
from app.replay.models import ExecutionOutcome
from app.trajectory.models import EventType

TOOL_V6 = uuid.uuid4()


def test_fake_executor_returns_default_outcome_and_records_invocation():
    executor = FakeReplayExecutor()
    outcome = executor.execute(
        event_type=EventType.TOOL_CALL, component_version_id=TOOL_V6, input={"a": 1}
    )
    assert outcome.status == "executed"
    assert executor.invocations == [
        {"event_type": EventType.TOOL_CALL, "component_version_id": TOOL_V6, "input": {"a": 1}}
    ]


def test_fake_executor_returns_keyed_response_for_specific_version():
    canned = ExecutionOutcome(status="executed", output={"authorized": True})
    executor = FakeReplayExecutor(responses={(EventType.TOOL_CALL, TOOL_V6): canned})
    outcome = executor.execute(
        event_type=EventType.TOOL_CALL, component_version_id=TOOL_V6, input={}
    )
    assert outcome is canned


def test_fake_executor_supports_only_configured_event_types():
    executor = FakeReplayExecutor(supported_types=[EventType.TOOL_CALL])
    assert executor.supports(EventType.TOOL_CALL)
    assert not executor.supports(EventType.MCP_REQUEST)


def test_fake_executor_never_reaches_a_network_call():
    """Structural guarantee: nothing in FakeReplayExecutor imports
    httpx/requests/sockets — it is dict lookups only."""

    import app.replay.executor as module

    source = module.__file__
    with open(source) as f:
        content = f.read()
    for forbidden in ("import httpx", "import requests", "import socket", "urlopen"):
        assert forbidden not in content


def test_registry_finds_first_supporting_executor():
    tool_only = FakeReplayExecutor(supported_types=[EventType.TOOL_CALL])
    mcp_only = FakeReplayExecutor(supported_types=[EventType.MCP_REQUEST])
    registry = ExecutorRegistry([tool_only, mcp_only])
    assert registry.find(EventType.TOOL_CALL) is tool_only
    assert registry.find(EventType.MCP_REQUEST) is mcp_only


def test_registry_returns_none_when_unsupported():
    registry = ExecutorRegistry([FakeReplayExecutor(supported_types=[EventType.TOOL_CALL])])
    assert registry.find(EventType.API_REQUEST) is None


def test_empty_registry_finds_nothing():
    assert ExecutorRegistry().find(EventType.TOOL_CALL) is None
