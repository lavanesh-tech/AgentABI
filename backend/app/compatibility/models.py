"""Pure data shapes for the compatibility engine — no SQLAlchemy, no
Pydantic, no I/O. `app/compatibility/analyzer.py` returns an
`AnalysisResult` built entirely from these; `app/services/
compatibility_service.py` is the only place that persists one.

Kept dependency-free deliberately (plain dataclasses + `enum.StrEnum`, like
`app/graph/models.py` in Phase 4) so the entire diff engine can be
imported and exercised without SQLAlchemy/FastAPI/Pydantic installed —
see docs/DECISIONS.md for why that mattered concretely in this project's
development environment.
"""

import enum
from dataclasses import dataclass, field
from typing import Any


class Direction(enum.StrEnum):
    """Which side of a contract a schema represents — compatibility is
    directional (see docs/DECISIONS.md): the same structural change means
    something different for a request body than for a response body.

    INPUT   — a request/argument contract; existing CALLERS must keep working.
    OUTPUT  — a response/return contract; existing CONSUMERS must keep working.
    NEUTRAL — direction unknown (e.g. a standalone `SCHEMA` component that
              isn't yet known to be used as anyone's input or output).
              Classified conservatively — see `rules.py`.
    """

    INPUT = "input"
    OUTPUT = "output"
    NEUTRAL = "neutral"


class ChangeType(enum.StrEnum):
    """Every kind of change this engine can detect. New members are a
    normal code change — see docs/DECISIONS.md for why this is a plain
    Python enum, not a Postgres native enum, at the persistence boundary."""

    # Structured schema changes (JSON-Schema-like input/output/standalone)
    FIELD_ADDED = "FIELD_ADDED"
    FIELD_REMOVED = "FIELD_REMOVED"
    REQUIRED_FIELD_ADDED = "REQUIRED_FIELD_ADDED"
    REQUIRED_FIELD_REMOVED = "REQUIRED_FIELD_REMOVED"
    TYPE_CHANGED = "TYPE_CHANGED"
    NULLABLE_TO_NON_NULLABLE = "NULLABLE_TO_NON_NULLABLE"
    NON_NULLABLE_TO_NULLABLE = "NON_NULLABLE_TO_NULLABLE"
    ENUM_VALUE_ADDED = "ENUM_VALUE_ADDED"
    ENUM_VALUE_REMOVED = "ENUM_VALUE_REMOVED"
    ENUM_NARROWED = "ENUM_NARROWED"
    ARRAY_ITEM_TYPE_CHANGED = "ARRAY_ITEM_TYPE_CHANGED"
    CONSTRAINT_CHANGED = "CONSTRAINT_CHANGED"

    # Generic config/mapping-level changes (MCP server settings, model
    # parameters, agent system_config, policy rules, workflow config, ...)
    CONFIG_FIELD_ADDED = "CONFIG_FIELD_ADDED"
    CONFIG_FIELD_REMOVED = "CONFIG_FIELD_REMOVED"
    VALUE_CHANGED = "VALUE_CHANGED"

    # Prompt
    CONTENT_CHANGED = "CONTENT_CHANGED"
    VARIABLE_ADDED = "VARIABLE_ADDED"
    VARIABLE_REMOVED = "VARIABLE_REMOVED"

    # Model
    PROVIDER_CHANGED = "PROVIDER_CHANGED"
    MODEL_IDENTIFIER_CHANGED = "MODEL_IDENTIFIER_CHANGED"
    PARAMETER_CHANGED = "PARAMETER_CHANGED"

    # Agent
    MODEL_REF_CHANGED = "MODEL_REF_CHANGED"
    PROMPT_REF_CHANGED = "PROMPT_REF_CHANGED"
    TOOL_ADDED = "TOOL_ADDED"
    TOOL_REMOVED = "TOOL_REMOVED"

    # Tool / MCP server metadata
    DESCRIPTION_CHANGED = "DESCRIPTION_CHANGED"
    ENDPOINT_CHANGED = "ENDPOINT_CHANGED"
    TRANSPORT_CHANGED = "TRANSPORT_CHANGED"
    SERVER_NAME_CHANGED = "SERVER_NAME_CHANGED"

    # API
    BASE_URL_CHANGED = "BASE_URL_CHANGED"
    METHOD_CHANGED = "METHOD_CHANGED"
    AUTH_CHANGED = "AUTH_CHANGED"

    # Workflow
    STEP_ADDED = "STEP_ADDED"
    STEP_REMOVED = "STEP_REMOVED"
    STEP_ORDER_CHANGED = "STEP_ORDER_CHANGED"
    REQUIRED_STEP_REMOVED = "REQUIRED_STEP_REMOVED"
    WORKFLOW_CONFIG_CHANGED = "WORKFLOW_CONFIG_CHANGED"

    # Policy
    RULE_ADDED = "RULE_ADDED"
    RULE_REMOVED = "RULE_REMOVED"
    RULE_CHANGED = "RULE_CHANGED"


class Classification(enum.StrEnum):
    """Per-change compatibility verdict. Never assigned by an LLM — always
    a deterministic lookup in `rules.py`."""

    COMPATIBLE = "compatible"
    POTENTIALLY_BREAKING = "potentially_breaking"
    BREAKING = "breaking"


class Severity(enum.StrEnum):
    """Per-change severity. CRITICAL is reserved for changes that are
    certain to break every existing caller/consumer (e.g. a brand-new
    required input field with no prior default) — see docs/DECISIONS.md
    for why that's distinct from HIGH (likely, not certain, to break)."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CompatibilityStatus(enum.StrEnum):
    """Scan-level rollup, derived deterministically from the worst
    classification among a scan's changes. This is a compatibility FACT,
    not a deployment decision — PASS/WARN/BLOCK is Phase 11's job."""

    COMPATIBLE = "compatible"
    WARNING = "warning"
    BREAKING = "breaking"


@dataclass(frozen=True, slots=True)
class Change:
    """One structurally detected difference between a baseline and
    candidate version. Never reduced to a human-readable string only —
    `path`/`change_type`/`classification`/`severity` are what later
    phases (blast radius correlation, replay selection, risk scoring,
    GitHub reporting) actually consume; `message` is a convenience for
    display, `evidence` carries whatever extra structured detail the
    specific change type produced (e.g. the exact enum values added or
    removed)."""

    change_type: ChangeType
    path: str
    classification: Classification
    severity: Severity
    message: str
    old_value: Any | None = None
    new_value: Any | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """The complete, deterministic output of comparing one baseline
    content dict against one candidate content dict for a given
    `ComponentType`. Contains no database identifiers — `AnalysisResult`
    is pure computation; `app/services/compatibility_service.py` is what
    turns it into a persisted `CompatibilityScan`/`ScanChange` row set."""

    status: CompatibilityStatus
    changes: tuple[Change, ...]

    @property
    def total_changes(self) -> int:
        return len(self.changes)

    @property
    def classification_counts(self) -> dict[str, int]:
        counts = dict.fromkeys((c.value for c in Classification), 0)
        for change in self.changes:
            counts[change.classification.value] += 1
        return counts

    @property
    def severity_counts(self) -> dict[str, int]:
        counts = dict.fromkeys((s.value for s in Severity), 0)
        for change in self.changes:
            counts[change.severity.value] += 1
        return counts
