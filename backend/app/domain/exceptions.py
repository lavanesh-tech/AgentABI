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
