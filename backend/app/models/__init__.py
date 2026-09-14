"""Import every ORM model here so `Base.metadata` is fully populated
(mapper relationships between modules only resolve once all target classes
have been imported) — Alembic's `env.py` imports this package for exactly
that reason, and so does anything that needs `Base.metadata.tables`.
"""

from app.models.audit_event import AuditEvent
from app.models.base import Base
from app.models.compatibility_scan import CompatibilityScan
from app.models.component import Component
from app.models.component_version import ComponentVersion
from app.models.github_webhook_delivery import GitHubWebhookDelivery
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrganizationRole
from app.models.project import Project
from app.models.replay_run import ReplayRun
from app.models.replay_step import ReplayStep
from app.models.scan_change import ScanChange
from app.models.trajectory import Trajectory
from app.models.trajectory_event import TrajectoryEvent
from app.models.user import User

__all__ = [
    "AuditEvent",
    "Base",
    "CompatibilityScan",
    "Component",
    "ComponentVersion",
    "GitHubWebhookDelivery",
    "Organization",
    "OrganizationMember",
    "OrganizationRole",
    "Project",
    "ReplayRun",
    "ReplayStep",
    "ScanChange",
    "Trajectory",
    "TrajectoryEvent",
    "User",
]
