"""BlastRadiusService — "if component X changes, what breaks?"

Deliberately implemented as plain, deterministic Python breadth-first
search over `GraphRepository.list_direct_dependents` one hop at a time,
rather than a single Cypher variable-length-path query. See
docs/DECISIONS.md for the full rationale; in short:

* it keeps cycle detection, deduplication, and the max-depth cutoff
  fully explicit and independently unit-testable (via
  `tests/fakes.py`'s `FakeGraphRepository`) instead of hidden inside a
  Cypher path expression;
* it never uses an LLM or any heuristic — the traversal is deterministic
  graph reachability, nothing else;
* it degrades gracefully to whatever `GraphRepository` implementation is
  supplied, real or in-memory.
"""

import uuid
from collections import deque
from dataclasses import dataclass, field

from app.domain.enums import ComponentType
from app.domain.exceptions import GraphComponentNotFound
from app.graph.repository import GraphRepository

DEFAULT_MAX_DEPTH = 10


@dataclass(frozen=True, slots=True)
class BlastRadiusEntry:
    """One component reachable (transitively) from the queried component
    by following dependent edges, plus how it was reached."""

    component_id: uuid.UUID
    component_type: ComponentType
    name: str
    slug: str
    depth: int
    path: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class BlastRadiusResult:
    component_id: uuid.UUID
    max_depth: int
    direct_dependents: tuple[BlastRadiusEntry, ...]
    transitive_dependents: tuple[BlastRadiusEntry, ...]
    affected_by_type: dict[ComponentType, tuple[BlastRadiusEntry, ...]] = field(
        default_factory=dict
    )

    @property
    def total_affected(self) -> int:
        return len(self.transitive_dependents)


class BlastRadiusService:
    def __init__(self, graph: GraphRepository) -> None:
        self._graph = graph

    async def compute(
        self,
        project_id: uuid.UUID,
        component_id: uuid.UUID,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> BlastRadiusResult:
        """BFS over dependents (incoming edges), starting at
        `component_id`. `max_depth` bounds how many hops are followed
        (1 = direct dependents only). A `visited` set keyed by
        component_id guarantees termination and de-duplication even on a
        cyclic graph (e.g. A depends on B depends on A): each component
        is enqueued and yielded at most once, at the depth it was first
        reached — the shortest path, since this is a breadth-first, not
        depth-first, search.
        """

        if max_depth < 1:
            raise ValueError("max_depth must be at least 1")

        root = await self._graph.get_component_node(project_id, component_id)
        if root is None:
            raise GraphComponentNotFound(component_id)

        visited: set[uuid.UUID] = {component_id}
        queue: deque[tuple[uuid.UUID, int, tuple[uuid.UUID, ...]]] = deque(
            [(component_id, 0, (component_id,))]
        )
        entries: list[BlastRadiusEntry] = []

        while queue:
            current_id, depth, path = queue.popleft()
            if depth >= max_depth:
                continue

            dependents = await self._graph.list_direct_dependents(project_id, current_id)
            # Deterministic ordering: dependents are sorted by
            # component_id regardless of what order the repository
            # returned them in, so repeated calls against the same graph
            # state always produce the same entry order.
            for edge in sorted(dependents, key=lambda e: e.component_id):
                if edge.component_id in visited:
                    continue
                visited.add(edge.component_id)
                next_depth = depth + 1
                next_path = path + (edge.component_id,)
                entries.append(
                    BlastRadiusEntry(
                        component_id=edge.component_id,
                        component_type=edge.component_type,
                        name=edge.name,
                        slug=edge.slug,
                        depth=next_depth,
                        path=next_path,
                    )
                )
                queue.append((edge.component_id, next_depth, next_path))

        direct = tuple(e for e in entries if e.depth == 1)
        affected_by_type: dict[ComponentType, list[BlastRadiusEntry]] = {}
        for entry in entries:
            affected_by_type.setdefault(entry.component_type, []).append(entry)

        return BlastRadiusResult(
            component_id=component_id,
            max_depth=max_depth,
            direct_dependents=direct,
            transitive_dependents=tuple(entries),
            affected_by_type={k: tuple(v) for k, v in affected_by_type.items()},
        )
