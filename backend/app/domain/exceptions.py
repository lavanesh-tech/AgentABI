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
