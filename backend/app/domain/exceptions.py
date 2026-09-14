"""Domain/application exceptions for the component registry.

Raised by the service layer, translated to HTTP responses in exactly one
place (`app/api/v1/errors.py`) rather than scattered try/except blocks in
route functions. Route handlers should never catch SQLAlchemy exceptions
directly — that's the service layer's job, and it never leaks database
internals (constraint names, driver error text) to callers.
"""

from typing import Any


class AgentABIError(Exception):
    """Base class for all AgentABI domain errors."""


class NotFoundError(AgentABIError):
    """Base class for "requested resource does not exist" errors. Mapped
    to HTTP 404."""


class ConflictError(AgentABIError):
    """Base class for "request conflicts with existing state" errors.
    Mapped to HTTP 409."""


class ProjectNotFound(NotFoundError):
    def __init__(self, project_id: Any) -> None:
        super().__init__(f"Project {project_id} not found")
        self.project_id = project_id


class ComponentNotFound(NotFoundError):
    def __init__(self, component_id: Any) -> None:
        super().__init__(f"Component {component_id} not found")
        self.component_id = component_id


class DuplicateComponent(ConflictError):
    def __init__(self, project_id: Any, component_type: Any, slug: str) -> None:
        super().__init__(
            f"Component with type={component_type!r} slug={slug!r} "
            f"already exists in project {project_id}"
        )
        self.project_id = project_id
        self.component_type = component_type
        self.slug = slug


class ComponentVersionNotFound(NotFoundError):
    def __init__(self, component_id: Any, version: str) -> None:
        super().__init__(f"Version {version!r} not found for component {component_id}")
        self.component_id = component_id
        self.version = version


class DuplicateComponentVersion(ConflictError):
    def __init__(self, component_id: Any, version: str) -> None:
        super().__init__(f"Version {version!r} already exists for component {component_id}")
        self.component_id = component_id
        self.version = version


class InvalidComponentContent(AgentABIError):
    """Raised when a version's content fails type-specific Pydantic
    validation for its component_type. Mapped to HTTP 422."""

    def __init__(self, component_type: Any, detail: str) -> None:
        super().__init__(f"Invalid content for component_type={component_type!r}: {detail}")
        self.component_type = component_type
        self.detail = detail


class GraphComponentNotFound(NotFoundError):
    """Raised when an operation needs a component's graph node (e.g.
    creating a dependency, blast-radius traversal) but it hasn't been
    synced from PostgreSQL into Neo4j yet via
    `DependencyGraphService.sync_component`."""

    def __init__(self, component_id: Any) -> None:
        super().__init__(f"Component {component_id} has not been synced into the graph yet")
        self.component_id = component_id


class InvalidDependencyRelationship(AgentABIError):
    """Raised when a requested (source_type, relationship_type, target_type)
    triple isn't one of the shapes `app/domain/relationship_rules.py`
    allows — e.g. a Model CALLing a Workflow. Mapped to HTTP 422."""

    def __init__(self, source_type: Any, relationship_type: Any, target_type: Any) -> None:
        super().__init__(
            f"{relationship_type!r} from {source_type!r} to {target_type!r} "
            "is not a valid dependency relationship"
        )
        self.source_type = source_type
        self.relationship_type = relationship_type
        self.target_type = target_type


class GraphUnavailable(AgentABIError):
    """Raised when Neo4j can't be reached at all (connection refused,
    auth failure, timeout). Mapped to HTTP 503 — distinct from 4xx errors,
    since the request itself may well be valid and just needs a retry once
    the graph database is reachable again."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Graph database unavailable: {detail}")
        self.detail = detail


class CompatibilityScanNotFound(NotFoundError):
    def __init__(self, scan_id: Any) -> None:
        super().__init__(f"Compatibility scan {scan_id} not found")
        self.scan_id = scan_id


class InvalidCompatibilityComparison(AgentABIError):
    """Raised when a requested baseline/candidate comparison doesn't make
    sense — e.g. the two versions belong to different components (the
    "same-component rule": Phase 5 §19). Mapped to HTTP 422."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Invalid compatibility comparison: {detail}")
        self.detail = detail


class UnsupportedCompatibilityType(AgentABIError):
    """Raised when `component_type` has no deterministic comparison
    defined yet (currently: `PROVIDER` — see docs/DECISIONS.md). Mapped to
    HTTP 422, distinct from `InvalidCompatibilityComparison`: the request
    itself is well-formed, this component type just isn't supported yet."""

    def __init__(self, component_type: Any) -> None:
        super().__init__(
            f"No compatibility comparison defined for component_type={component_type!r}"
        )
        self.component_type = component_type


class SchemaNormalizationError(AgentABIError):
    """Raised when a stored schema payload is too malformed to normalize/
    diff deterministically (e.g. a non-dict, non-boolean schema node).
    Mapped to HTTP 422 — this is a data-quality problem with the stored
    content, not a server error."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Cannot normalize schema: {detail}")
        self.detail = detail


class TrajectoryNotFound(NotFoundError):
    def __init__(self, trajectory_id: Any) -> None:
        super().__init__(f"Trajectory {trajectory_id} not found")
        self.trajectory_id = trajectory_id


class TrajectoryAlreadyExists(ConflictError):
    """Raised when a `start_trajectory` call's `external_run_id` already
    identifies a different trajectory *and* the new request's declared
    identifying fields (workflow version, environment) conflict with the
    existing one — an exact-duplicate retry instead returns the existing
    trajectory (see docs/DECISIONS.md). Mapped to HTTP 409."""

    def __init__(self, project_id: Any, external_run_id: str) -> None:
        super().__init__(
            f"Trajectory with external_run_id={external_run_id!r} already exists in "
            f"project {project_id} with conflicting details"
        )
        self.project_id = project_id
        self.external_run_id = external_run_id


class TrajectoryTerminal(ConflictError):
    """Raised when `append_event` targets a trajectory that is no longer
    RUNNING. Mapped to HTTP 409 — distinct from `InvalidTrajectoryTransition`,
    which is about the trajectory's own status-transition operations, not
    event ingestion."""

    def __init__(self, trajectory_id: Any, status: Any) -> None:
        super().__init__(
            f"Trajectory {trajectory_id} is {status!r} (terminal); cannot append events"
        )
        self.trajectory_id = trajectory_id
        self.status = status


class InvalidTrajectoryTransition(ConflictError):
    """Raised by `complete_trajectory`/`fail_trajectory` when the
    trajectory isn't RUNNING — e.g. completing an already-failed
    trajectory. Mapped to HTTP 409."""

    def __init__(self, trajectory_id: Any, current_status: Any, target_status: Any) -> None:
        super().__init__(
            f"Trajectory {trajectory_id} cannot transition from {current_status!r} "
            f"to {target_status!r}"
        )
        self.trajectory_id = trajectory_id
        self.current_status = current_status
        self.target_status = target_status


class InvalidTrajectoryEvent(AgentABIError):
    """Raised when an event's shape is structurally nonsensical for its
    `event_type` (see `app/trajectory/validation.py`), or when a
    component/component-version reference doesn't resolve within the
    trajectory's project. Mapped to HTTP 422."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class DuplicateTrajectoryEvent(ConflictError):
    """Raised when an `append_event` call reuses an `external_event_id`
    already recorded on this trajectory with *different* event data (an
    exact-duplicate retry is instead idempotent — see
    docs/DECISIONS.md). Mapped to HTTP 409."""

    def __init__(self, trajectory_id: Any, external_event_id: str) -> None:
        super().__init__(
            f"external_event_id={external_event_id!r} already recorded on trajectory "
            f"{trajectory_id} with different event data"
        )
        self.trajectory_id = trajectory_id
        self.external_event_id = external_event_id


class TrajectoryPayloadTooLarge(AgentABIError):
    """Raised when a single event payload field exceeds the hard size
    ceiling (`app/trajectory/payload_limits.py`) — too large even to
    store as a truncated representation. Mapped to HTTP 422."""

    def __init__(self, field_name: str, size_bytes: int, limit_bytes: int) -> None:
        super().__init__(
            f"Event field {field_name!r} is {size_bytes} bytes, exceeding the "
            f"{limit_bytes}-byte hard limit"
        )
        self.field_name = field_name
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


class ReplayNotFound(NotFoundError):
    def __init__(self, replay_id: Any) -> None:
        super().__init__(f"Replay {replay_id} not found")
        self.replay_id = replay_id


class ReplayAlreadyExists(ConflictError):
    """Raised when a `create_replay` call's `idempotency_key` already
    identifies a different replay in this project *and* the new
    request's identifying fields (trajectory/baseline/candidate)
    conflict with the existing one — an exact-duplicate retry instead
    returns the existing replay (mirrors Phase 6 ADR-029). Mapped to
    HTTP 409."""

    def __init__(self, project_id: Any, idempotency_key: str) -> None:
        super().__init__(
            f"Replay with idempotency_key={idempotency_key!r} already exists in "
            f"project {project_id} with conflicting details"
        )
        self.project_id = project_id
        self.idempotency_key = idempotency_key


class InvalidReplayTransition(ConflictError):
    """Raised when `execute_replay` targets a replay that isn't PENDING
    (already RUNNING/COMPLETED/FAILED). Mapped to HTTP 409."""

    def __init__(self, replay_id: Any, current_status: Any, target_status: Any) -> None:
        super().__init__(
            f"Replay {replay_id} cannot transition from {current_status!r} to {target_status!r}"
        )
        self.replay_id = replay_id
        self.current_status = current_status
        self.target_status = target_status


class InvalidReplaySubstitution(AgentABIError):
    """Raised when a requested baseline->candidate substitution is
    meaningless: candidate/baseline don't share a component, the source
    trajectory never actually invoked the baseline version, the source
    trajectory isn't COMPLETED, or a component/version reference doesn't
    belong to the resolved project. Mapped to HTTP 422."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ReplayExecutorUnavailable(AgentABIError):
    """Raised when `execute_replay` reaches a step that needs a real
    executor for its event type and none is registered — Phase 7 wires
    no production executors (there is nothing real to execute until
    Phase 8/9's provider adapters and later tool/MCP/API integrations
    exist), so this is the expected, explicit failure mode rather than a
    silent no-op. Mapped to HTTP 503."""

    def __init__(self, replay_id: Any, event_type: Any) -> None:
        super().__init__(
            f"No executor available for event_type={event_type!r} while executing replay "
            f"{replay_id}"
        )
        self.replay_id = replay_id
        self.event_type = event_type


class ReplayExecutionFailed(AgentABIError):
    """Raised when an executor itself raises unexpectedly (a transport/
    programming error), distinct from a structured `ExecutionOutcome`
    with `status="failed"` — the latter is normal recorded evidence
    (the candidate ran and failed), not an exception. Mapped to HTTP
    422; the replay run is transitioned to FAILED before this is
    raised, so state stays consistent."""

    def __init__(self, replay_id: Any, detail: str) -> None:
        super().__init__(f"Replay {replay_id} execution failed: {detail}")
        self.replay_id = replay_id
        self.detail = detail


class AuthenticationError(AgentABIError):
    """Base class for "the request's credentials could not be
    established" errors. Mapped to HTTP 401 — distinct from
    `NotFoundError`/`ConflictError`: authentication failures never leak
    whether a resource exists, only that the caller isn't recognized."""


class AuthenticationRequired(AuthenticationError):
    """Raised when a protected endpoint receives no Bearer token at
    all."""

    def __init__(self) -> None:
        super().__init__("Authentication required")


class InvalidToken(AuthenticationError):
    """Raised for any structurally/cryptographically invalid token:
    malformed, wrong signature, wrong issuer/audience, missing required
    claims. Deliberately one error for all of these (Phase A spec §10) —
    telling a caller *which* validation failed would help an attacker
    probe the verifier; the client-facing message is uniform."""

    def __init__(self, detail: str = "Invalid authentication token") -> None:
        super().__init__(detail)


class ExpiredToken(AuthenticationError):
    """Raised when a token's `exp` claim has passed. Kept distinct from
    `InvalidToken` only because "your session expired, log in again" is
    a meaningfully different client action than "this token is
    garbage" — the HTTP mapping is identical (401)."""

    def __init__(self) -> None:
        super().__init__("Authentication token has expired")


class UnknownUser(AuthenticationError):
    """Raised when a token's `sub` claim decodes and verifies
    successfully but no longer resolves to an existing user (e.g. the
    account was deleted after the token was issued). A valid signature
    is not, by itself, proof of a live identity."""

    def __init__(self) -> None:
        super().__init__("Authentication token does not reference a known user")


class DisabledUser(AuthenticationError):
    """Raised when a token resolves to a real user whose `is_active` is
    false. A valid signature and a real account are still not enough —
    the account must currently be allowed to authenticate."""

    def __init__(self) -> None:
        super().__init__("User account is disabled")
