"""Pure unit tests for `app/replay/planner.py`. No database, no I/O.

Includes the Phase 7 acceptance case: a 7-event checkout trajectory
(AGENT_STARTED CheckoutAgent v3 -> MODEL_REQUEST -> MODEL_RESPONSE ->
TOOL_CALL AuthorizePaymentTool v5 -> TOOL_RESPONSE -> STATE_WRITE ->
AGENT_COMPLETED) replayed against AuthorizePaymentTool v5 -> v6.
"""

import uuid

import pytest

from app.domain.exceptions import InvalidReplaySubstitution
from app.replay.models import StepKind, TrajectoryEventView
from app.replay.planner import build_replay_plan
from app.trajectory.models import EventType

AGENT_ID = uuid.uuid4()
AGENT_V3 = uuid.uuid4()
TOOL_ID = uuid.uuid4()
TOOL_V5 = uuid.uuid4()
TOOL_V6 = uuid.uuid4()
OTHER_TOOL_ID = uuid.uuid4()
OTHER_TOOL_V1 = uuid.uuid4()


def _checkout_events() -> list[TrajectoryEventView]:
    return [
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=1,
            event_type=EventType.AGENT_STARTED,
            component_id=AGENT_ID,
            component_version_id=AGENT_V3,
            input=None,
            output=None,
        ),
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=2,
            event_type=EventType.MODEL_REQUEST,
            component_id=None,
            component_version_id=None,
            input={"messages": []},
            output=None,
        ),
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=3,
            event_type=EventType.MODEL_RESPONSE,
            component_id=None,
            component_version_id=None,
            input=None,
            output={"tool_calls": [{"name": "authorize_payment"}]},
        ),
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=4,
            event_type=EventType.TOOL_CALL,
            component_id=TOOL_ID,
            component_version_id=TOOL_V5,
            input={
                "invocation_id": "call-1",
                "arguments": {"customer_id": "customer-991", "amount": 125.0, "currency": "USD"},
            },
            output=None,
        ),
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=5,
            event_type=EventType.TOOL_RESPONSE,
            component_id=TOOL_ID,
            component_version_id=TOOL_V5,
            input={"invocation_id": "call-1"},
            output={"authorized": True, "authorization_id": "auth-829"},
        ),
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=6,
            event_type=EventType.STATE_WRITE,
            component_id=None,
            component_version_id=None,
            input={"key": "order_status", "current_value": "PAYMENT_AUTHORIZED"},
            output=None,
        ),
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=7,
            event_type=EventType.AGENT_COMPLETED,
            component_id=AGENT_ID,
            component_version_id=AGENT_V3,
            input=None,
            output=None,
        ),
    ]


def _plan():
    return build_replay_plan(
        _checkout_events(),
        baseline_component_id=TOOL_ID,
        baseline_version_id=TOOL_V5,
        candidate_version_id=TOOL_V6,
    )


def test_plan_has_one_step_per_event_in_sequence_order():
    plan = _plan()
    assert [s.sequence_number for s in plan.steps] == [1, 2, 3, 4, 5, 6, 7]


def test_tool_call_using_baseline_is_substituted_with_candidate():
    plan = _plan()
    step = next(s for s in plan.steps if s.sequence_number == 4)
    assert step.kind == StepKind.SUBSTITUTED_EXECUTION
    assert step.execution_component_version_id == TOOL_V6
    # Historical invocation context (arguments) is preserved verbatim.
    assert step.historical_input["arguments"] == {
        "customer_id": "customer-991",
        "amount": 125.0,
        "currency": "USD",
    }


def test_paired_tool_response_is_skipped_with_justification():
    plan = _plan()
    step = next(s for s in plan.steps if s.sequence_number == 5)
    assert step.kind == StepKind.SKIPPED
    assert step.justification is not None


def test_model_events_require_provider_execution():
    plan = _plan()
    for seq in (2, 3):
        step = next(s for s in plan.steps if s.sequence_number == seq)
        assert step.kind == StepKind.PROVIDER_EXECUTION_REQUIRED


def test_agent_and_state_events_are_reused_evidence():
    plan = _plan()
    for seq in (1, 6, 7):
        step = next(s for s in plan.steps if s.sequence_number == seq)
        assert step.kind == StepKind.REUSED_EVIDENCE


def test_only_the_matching_component_version_is_substituted():
    """A tool invocation of a *different* component must never be
    substituted just because some other event in the trajectory used the
    baseline version (Phase 7 §4 — reject meaningless/unrelated
    substitutions)."""

    events = _checkout_events() + [
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=8,
            event_type=EventType.TOOL_CALL,
            component_id=OTHER_TOOL_ID,
            component_version_id=OTHER_TOOL_V1,
            input={"invocation_id": "call-2", "arguments": {}},
            output=None,
        ),
    ]
    plan = build_replay_plan(
        events,
        baseline_component_id=TOOL_ID,
        baseline_version_id=TOOL_V5,
        candidate_version_id=TOOL_V6,
    )
    other_step = next(s for s in plan.steps if s.sequence_number == 8)
    assert other_step.kind == StepKind.REUSED_EVIDENCE


def test_baseline_never_used_raises_invalid_substitution():
    events = [
        TrajectoryEventView(
            id=uuid.uuid4(),
            sequence_number=1,
            event_type=EventType.RUN_STARTED,
            component_id=None,
            component_version_id=None,
            input=None,
            output=None,
        )
    ]
    with pytest.raises(InvalidReplaySubstitution):
        build_replay_plan(
            events,
            baseline_component_id=TOOL_ID,
            baseline_version_id=TOOL_V5,
            candidate_version_id=TOOL_V6,
        )


def test_plan_is_deterministic_across_calls():
    plan_a = _plan()
    plan_b = _plan()
    kinds_a = [(s.sequence_number, s.kind) for s in plan_a.steps]
    kinds_b = [(s.sequence_number, s.kind) for s in plan_b.steps]
    assert kinds_a == kinds_b


def test_events_out_of_order_are_still_planned_in_sequence_order():
    events = list(reversed(_checkout_events()))
    plan = build_replay_plan(
        events,
        baseline_component_id=TOOL_ID,
        baseline_version_id=TOOL_V5,
        candidate_version_id=TOOL_V6,
    )
    assert [s.sequence_number for s in plan.steps] == [1, 2, 3, 4, 5, 6, 7]
