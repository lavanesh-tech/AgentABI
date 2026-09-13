"""Dependency graph API — sync a component into Neo4j, manage dependency
edges between synced components, and query direct dependencies/dependents
and blast radius.

Thin by design: routes only translate HTTP <-> Pydantic <-> service calls.
All graph logic (validation, traversal, tenant scoping) lives in
`DependencyGraphService`/`BlastRadiusService`; all Cypher lives in
`app/graph/repository.py`. Routes never see a raw Neo4j `Record`/`Node`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domain.enums import ComponentType, DependencyRelationshipType
from app.graph.client import get_driver
from app.graph.models import ComponentNode, DependencyEdge
from app.graph.repository import Neo4jGraphRepository
from app.services.blast_radius import BlastRadiusEntry, BlastRadiusResult, BlastRadiusService
from app.services.component_registry import ComponentRegistryService
from app.services.dependency_graph import DependencyGraphService

router = APIRouter(prefix="/projects/{project_id}", tags=["graph"])


# --- Schemas -----------------------------------------------------------


class ComponentNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component_id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    component_type: ComponentType
    name: str
    slug: str
    version: str
    checksum: str
    synced_at: str

    @classmethod
    def from_node(cls, node: ComponentNode) -> "ComponentNodeResponse":
        return cls(
            component_id=node.component_id,
            project_id=node.project_id,
            organization_id=node.organization_id,
            component_type=node.component_type,
            name=node.name,
            slug=node.slug,
            version=node.version,
            checksum=node.checksum,
            synced_at=node.synced_at.isoformat(),
        )


class DependencyEdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    component_id: uuid.UUID
    component_type: ComponentType
    name: str
    slug: str
    relationship_type: DependencyRelationshipType

    @classmethod
    def from_edge(cls, edge: DependencyEdge) -> "DependencyEdgeResponse":
        return cls(
            component_id=edge.component_id,
            component_type=edge.component_type,
            name=edge.name,
            slug=edge.slug,
            relationship_type=edge.relationship_type,
        )


class DependencyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    target_id: uuid.UUID
    relationship_type: DependencyRelationshipType


class BlastRadiusEntryResponse(BaseModel):
    component_id: uuid.UUID
    component_type: ComponentType
    name: str
    slug: str
    depth: int
    path: list[uuid.UUID]

    @classmethod
    def from_entry(cls, entry: BlastRadiusEntry) -> "BlastRadiusEntryResponse":
        return cls(
            component_id=entry.component_id,
            component_type=entry.component_type,
            name=entry.name,
            slug=entry.slug,
            depth=entry.depth,
            path=list(entry.path),
        )


class BlastRadiusResponse(BaseModel):
    component_id: uuid.UUID
    max_depth: int
    total_affected: int
    direct_dependents: list[BlastRadiusEntryResponse]
    transitive_dependents: list[BlastRadiusEntryResponse]
    affected_by_type: dict[ComponentType, list[BlastRadiusEntryResponse]]

    @classmethod
    def from_result(cls, result: BlastRadiusResult) -> "BlastRadiusResponse":
        return cls(
            component_id=result.component_id,
            max_depth=result.max_depth,
            total_affected=result.total_affected,
            direct_dependents=[
                BlastRadiusEntryResponse.from_entry(e) for e in result.direct_dependents
            ],
            transitive_dependents=[
                BlastRadiusEntryResponse.from_entry(e) for e in result.transitive_dependents
            ],
            affected_by_type={
                component_type: [BlastRadiusEntryResponse.from_entry(e) for e in entries]
                for component_type, entries in result.affected_by_type.items()
            },
        )


# --- Dependencies --------------------------------------------------------


def get_dependency_graph_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DependencyGraphService:
    registry = ComponentRegistryService(session)
    graph = Neo4jGraphRepository(get_driver())
    return DependencyGraphService(registry, graph)


def get_blast_radius_service() -> BlastRadiusService:
    return BlastRadiusService(Neo4jGraphRepository(get_driver()))


GraphServiceDep = Annotated[DependencyGraphService, Depends(get_dependency_graph_service)]
BlastRadiusServiceDep = Annotated[BlastRadiusService, Depends(get_blast_radius_service)]


# --- Routes --------------------------------------------------------------


@router.post(
    "/components/{component_id}/graph/sync",
    response_model=ComponentNodeResponse,
    status_code=status.HTTP_200_OK,
)
async def sync_component(
    project_id: uuid.UUID, component_id: uuid.UUID, service: GraphServiceDep
) -> ComponentNodeResponse:
    node = await service.sync_component(project_id, component_id)
    return ComponentNodeResponse.from_node(node)


@router.post(
    "/graph/dependencies",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def create_dependency(
    project_id: uuid.UUID, payload: DependencyCreateRequest, service: GraphServiceDep
) -> None:
    await service.create_dependency(
        project_id, payload.source_id, payload.target_id, payload.relationship_type
    )


@router.delete(
    "/graph/dependencies",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_dependency(
    project_id: uuid.UUID, payload: DependencyCreateRequest, service: GraphServiceDep
) -> None:
    await service.delete_dependency(
        project_id, payload.source_id, payload.target_id, payload.relationship_type
    )


@router.get(
    "/components/{component_id}/graph/dependencies",
    response_model=list[DependencyEdgeResponse],
)
async def list_dependencies(
    project_id: uuid.UUID, component_id: uuid.UUID, service: GraphServiceDep
) -> list[DependencyEdgeResponse]:
    edges = await service.list_dependencies(project_id, component_id)
    return [DependencyEdgeResponse.from_edge(e) for e in edges]


@router.get(
    "/components/{component_id}/graph/dependents",
    response_model=list[DependencyEdgeResponse],
)
async def list_dependents(
    project_id: uuid.UUID, component_id: uuid.UUID, service: GraphServiceDep
) -> list[DependencyEdgeResponse]:
    edges = await service.list_dependents(project_id, component_id)
    return [DependencyEdgeResponse.from_edge(e) for e in edges]


@router.get(
    "/components/{component_id}/graph/blast-radius",
    response_model=BlastRadiusResponse,
)
async def get_blast_radius(
    project_id: uuid.UUID,
    component_id: uuid.UUID,
    service: BlastRadiusServiceDep,
    max_depth: int = Query(default=10, ge=1, le=50),
) -> BlastRadiusResponse:
    result = await service.compute(project_id, component_id, max_depth=max_depth)
    return BlastRadiusResponse.from_result(result)
