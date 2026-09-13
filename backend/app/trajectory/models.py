"""Pure domain model for trajectory recording — no SQLAlchemy/FastAPI/
Pydantic import anywhere in this module, matching the same testability
choice `app/compatibility/models.py` made in Phase 5: everything here is
stdlib dataclasses/enums, importable and unit-testable without a
database, an HTTP framework, or a validation library installed.

`EventType`/`TrajectoryStatus` are the closed, code-defined taxonomies
the spec asks for ("do not use arbitrary free-form strings"); the
`*Payload` dataclasses are optional, convenience-typed constructors for
the free-form `input`/`output` JSONB fields `TrajectoryEvent` actually
stores — a provider-neutral core plus an `extra` bucket for anything
that doesn't fit, rather than one field per imaginable provider detail.
"""

import enum
from dataclasses import dataclass, field
from typing import Any


class EventType(enum.StrEnum):
    """The trajectory event taxonomy. `RUN_COMPLETED`/`RUN_FAILED` are
    reserved — they describe a trajectory-level status transition, which
    must go through `TrajectoryRecorderService.complete_trajectory`/
    `fail_trajectory`, not a generic `append_event` call (Phase 6 §23);
    `app/trajectory/validation.py` enforces this."""

    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_CALL = "tool_call"
    TOOL_RESPONSE = "tool_response"
    MCP_REQUEST = "mcp_request"
    MCP_RESPONSE = "mcp_response"
    API_REQUEST = "api_request"
    API_RESPONSE = "api_response"
    STATE_READ = "state_read"
    STATE_WRITE = "state_write"
    DECISION = "decision"
    STRUCTURED_OUTPUT = "structured_output"
    ERROR = "error"


class TrajectoryStatus(enum.StrEnum):
    """Deterministic trajectory lifecycle. Only two transitions are ever
    valid — RUNNING -> COMPLETED, RUNNING -> FAILED — centralized in
    `app/trajectory/transitions.py`, never re-implemented per endpoint."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@dataclass(frozen=True)
class ModelRequestPayload:
    """Convenience constructor for a `MODEL_REQUEST` event's `input`
    payload. Only replay-relevant fields — no provider-specific request
    envelope modeling (Phase 6 §8)."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    structured_output: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(
            {
                "messages": self.messages,
                "parameters": self.parameters,
                "tools": self.tools,
                "structured_output": self.structured_output,
            }
        )


@dataclass(frozen=True)
class ModelResponsePayload:
    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    structured_output: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(
            {
                "content": self.content,
                "tool_calls": self.tool_calls,
                "structured_output": self.structured_output,
                "finish_reason": self.finish_reason,
                "usage": self.usage,
            }
        )


@dataclass(frozen=True)
class ToolCallPayload:
    """A `TOOL_CALL` event's `input` payload. `invocation_id` is the
    caller-assigned identifier that links this call to its eventual
    `TOOL_RESPONSE` — required (see `app/trajectory/validation.py`)."""

    invocation_id: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"invocation_id": self.invocation_id, "arguments": self.arguments}


@dataclass(frozen=True)
class ToolResponsePayload:
    """A `TOOL_RESPONSE` event's `input` (linkage) + `output`/`error`
    (result). `invocation_id` must match the originating `TOOL_CALL`."""

    invocation_id: str
    result: Any = None
    error: dict[str, Any] | None = None

    def to_input_dict(self) -> dict[str, Any]:
        return {"invocation_id": self.invocation_id}

    def to_output_dict(self) -> dict[str, Any] | None:
        return None if self.result is None else {"result": self.result}


@dataclass(frozen=True)
class StatePayload:
    """A `STATE_READ`/`STATE_WRITE` event's `input` payload. `key` is
    required (see `app/trajectory/validation.py`)."""

    key: str
    scope: str | None = None
    previous_value: Any = None
    current_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        # previous_value/current_value are kept even when None — for a
        # state event, "the value is None" and "no value was recorded"
        # are different facts, unlike the other payloads' optional
        # fields above, so this doesn't route through `_drop_none`.
        payload: dict[str, Any] = {
            "key": self.key,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
        }
        if self.scope is not None:
            payload["scope"] = self.scope
        return payload
