"""Import every ORM model here so `Base.metadata` is fully populated
(mapper relationships between modules only resolve once all target classes
have been imported) — Alembic's `env.py` imports this package for exactly
that reason, and so does anything that needs `Base.metadata.tables`.
"""

from app.models.base import Base
from app.models.component import Component
from app.models.component_version import ComponentVersion
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrganizationRole
from app.models.project import Project
from app.models.user import User

__all__ = [
    "Base",
    "Component",
    "ComponentVersion",
    "Organization",
    "OrganizationMember",
    "OrganizationRole",
    "Project",
    "User",
]
