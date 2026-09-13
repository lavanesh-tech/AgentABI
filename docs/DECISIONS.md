# Architecture Decision Log

Short-form ADRs. Newest first.

## ADR-025 — Generic `diff_mapping()` fallback for component types Phase 3 didn't fully structure (2026-09-13)

**Context:** The Phase 5 spec asks for Workflow (steps/ordering), Policy
(rule/capability changes), MCP-server, and API comparison, but Phase 3's
`app/domain/component_content.py` models `WorkflowContent.definition` and
`PolicyContent.rules` as unstructured `dict`s, and `MCPServerContent`/
`APIContent` carry no schema field at all. Inventing structure the
registry doesn't actually have would be dishonest determinism — it would
look like real analysis of a contract that isn't there.

**Decision:** `app/compatibility/diff.py`'s `diff_mapping()` is a single,
generic, non-directional recursive dict differ (config field
added/removed/changed), reused by five of `analyzer.py`'s per-type
functions as their fallback path. For Workflow specifically,
`_diff_agent_tools`-style convention detection is attempted first — *if*
`definition` looks like `{"steps": [{"id"|"name", "required", ...}]}`,
step add/remove/reorder/required-removal is reported with real
`ChangeType`s; otherwise it falls back to `diff_mapping()` on the whole
`definition`. Policy, MCP-server config fields, and API's `auth`/`base_url`
go straight to `diff_mapping()`. This is a deliberate, documented scope
decision tied to what Phase 3 actually modeled, not a shortcut avoiding
real diffing — extending it just means giving these `ComponentType`s
richer `*Content` models later, at which point the same `diff_schemas()`
machinery already handles them for free.

## ADR-024 — Compatibility scan persistence: plain-VARCHAR `change_type`, unconditional immutability trigger, always-new-scan idempotency, same-component rule enforced twice (2026-09-13)

**`change_type` as `String(100)`, not a native Postgres enum:** unlike
`classification`/`severity`/`status`, which are small closed 3/5/3-member
sets, `ChangeType` already has ~40 members and is exactly the kind of
thing later phases (behavioral differential analysis, new schema-diff
rules) will keep extending. A native enum requires an `ALTER TYPE ... ADD
VALUE` migration per new member; a plain indexed `VARCHAR` makes adding a
change type a Python-only change to `app/compatibility/models.py`.

**Immutability trigger is unconditional, not column-scoped:** Phase 3's
`prevent_component_version_mutation()` (ADR-011) only blocks
`content`/`checksum` changes, deliberately allowing `metadata` updates.
Phase 5's `prevent_compatibility_evidence_mutation()` rejects *any* UPDATE
on `compatibility_scans`/`scan_changes` unconditionally, because — unlike
a component version, which has one genuinely mutable field — no column on
either compatibility table has a legitimate reason to change after the
scan completes; the whole row is the evidence.

**Idempotency: `run_scan` always creates a new historical row.** Two
`run_scan(project, component, "1", "2")` calls produce two distinct
`CompatibilityScan` rows, never a dedup/reuse of an existing one (proved
by `test_repeated_scans_create_separate_historical_rows`). Chosen
deliberately, not left as an accidental side effect of the lack of a
uniqueness constraint: a scan is an audit record of "this comparison ran
at this time," and later phases (replay evidence, release-risk decisions,
GitHub check-runs) need to attach to *the specific run that gated a
specific deployment*, not to "the latest scan of this pair." Re-running
is cheap (pure computation, no external calls) so there's no cost to
always recording history.

**Same-component rule enforced both structurally and defensively:** the
public `run_scan(project_id, component_id, baseline_version,
candidate_version)` signature takes one `component_id` for both version
lookups, so comparing two different components is unreachable through the
real API by construction. `_scan_from_versions` *additionally* asserts
`baseline.component_id == candidate.component_id` at runtime and raises
`InvalidCompatibilityComparison` if it ever isn't — independently
unit-tested by calling that private method directly with mismatched
components (`test_scan_from_versions_rejects_unrelated_components`). Two
enforcement layers because "structurally unreachable today" and "will
always stay unreachable as this code evolves" are different guarantees.

## ADR-023 — Directional compatibility classification, and reserving `CRITICAL` for one specific case (2026-09-13)

**Context:** The same structural change (e.g. "field removed") means
different things depending on whether the schema is something callers
send (input/request) or something callers receive (output/response).

**Decision:** `Direction` (`INPUT`/`OUTPUT`/`NEUTRAL`) is an explicit
parameter threaded through `diff_schemas()`/`classify()`, never inferred
from field names or component type. `analyzer.py` passes `INPUT` for a
tool/API's `input_schema`, `OUTPUT` for `output_schema`, and `NEUTRAL` for
a standalone `SCHEMA` component whose usage isn't known. The rules table
(`app/compatibility/rules.py`) encodes the asymmetry directly: adding a
required input field is breaking (new callers must supply it — existing
callers can't), removing a required input field is compatible (existing
callers already satisfy the stricter old contract); the reverse holds for
output — removing an output field is breaking (existing consumers may
read it), adding one is compatible. `NEUTRAL` is defined to never be more
lenient than the stricter of `INPUT`/`OUTPUT` for the same change type
(tested directly: `test_neutral_direction_is_never_more_lenient_than_
either_known_direction`), since with no known direction the safe
assumption is the more conservative one.

**`Severity.CRITICAL` is reserved for exactly one case:**
`(REQUIRED_FIELD_ADDED, Direction.INPUT)`. Every other breaking change is
at most `HIGH`. This is the one case the engine can assert with
*certainty*, not likelihood — any existing caller not already sending the
new required field is guaranteed to fail schema validation. Every other
breaking classification (type changes, enum narrowing, output field
removal) depends on how a specific consumer actually uses the data, which
Phase 5 explicitly cannot determine (that's replay/behavioral-diff work,
Phases 7/10) — so those stay `HIGH` rather than being inflated to
`CRITICAL`.

## ADR-022 — Phase 5 verification: the deterministic engine ran for real; persistence was verified by direct DDL, not through `pytest` (2026-09-13)

**Context:** Same sandbox restriction as every prior phase (ADR-005/006/
008/013/021) — `fastapi`/`sqlalchemy`/`pydantic`/`httpx`/`alembic` cannot
be installed here (PyPI returns 403), so the project's own `pytest` suite
cannot run end-to-end.

**What is materially better this phase:** the entire compatibility engine
(`app/compatibility/{models,schema_normalizer,rules,diff,analyzer}.py`) is
plain-dataclass, stdlib-only Python — no SQLAlchemy/Pydantic/FastAPI
import anywhere in that package. That made it possible to bypass
`tests/conftest.py` (which imports `httpx` at collection time) with
`pytest --noconftest` and run the real, installed standalone `pytest`
binary (`/root/.local/bin/pytest`, a `uv tool install`) directly against
`tests/test_schema_normalizer.py`, `test_rules.py`, `test_diff.py`, and
`test_analyzer.py`: **75/75 passed**, including the exact spec §31
acceptance case run through the generic engine (not hardcoded). This is a
strictly stronger verification story than Phase 4's manual `asyncio`
script, because it is the real pytest runner, not a substitute.

**What still could not run through pytest:** `test_compatibility_
service.py` (15 tests) and `test_compatibility_api.py` (11 tests) need the
`session`/`client`/`db_engine` fixtures, which require SQLAlchemy/
FastAPI/httpx — unavailable, so these files are written (and
`python3.12 -m py_compile`-clean) but not pytest-executed this session.

**What was verified instead, following the ADR-008 pattern:** migration
0003's full `upgrade()` was hand-transcribed to raw SQL (types, tables,
indexes, the `prevent_compatibility_evidence_mutation` trigger function
and both triggers) and run directly against a real local Postgres 16
(`agentabi_test`), on top of migrations 0001/0002 transcribed the same
way. Then, with real rows (the spec §31 tool contract: baseline
`{customer_id, amount, currency}` all required → candidate `{user_id,
amount}`), directly exercised: insert/select round-trip of a
`compatibility_scans` + 3 `scan_changes` rows including JSONB
`old_value`/`new_value`; both immutability triggers, each producing the
expected `ERROR: compatibility scan evidence is immutable once created`
on a raw `UPDATE`; the pre-existing unique-slug constraint; and
`ON DELETE CASCADE` from `projects` removing the scan and its changes.
All as expected — proving the DDL and constraints are correct Postgres,
same caveat as ADR-008: the Alembic *tool* itself wasn't exercised, only
the SQL it would produce. The schema was dropped and recreated cleanly
afterward; nothing persists between sessions in this sandbox.

**Action for the user (once run somewhere with normal PyPI access):**
```
cd backend && make install
alembic upgrade head
pytest tests/test_compatibility_service.py tests/test_compatibility_api.py -v
pytest tests/ -v   # full suite
mypy app
```

## ADR-021 — Phase 4 Neo4j/Docker verification gap: genuinely attempted, genuinely unavailable (2026-09-13)

**Context:** The Phase 4 spec explicitly requires a real attempt to run
Neo4j — via Docker or any other means — in both the cloud sandbox and (per
the user's move of the authoritative repo) the Mac, before concluding it
is unavailable, with exact commands documented if it truly isn't. This ADR
records exactly what was tried, in both places, this session.

**Cloud sandbox (`/home/claude/agentabi`):**
- `docker version` succeeds — a Docker daemon (`sudo -n dockerd`, 29.4.3)
  runs in this container, which was *not* true in earlier phases. This is
  new and worth recording.
- `docker pull hello-world` (and, by the same mechanism,
  `docker compose -f docker-compose.yml up -d neo4j`) fails:
  `403 Forbidden` from `registry-1.docker.io` — the same outbound-egress
  allowlist that blocks PyPI (`pypi.org`/`files.pythonhosted.org`) and apt
  (`archive.ubuntu.com`, confirmed 403 again this phase via
  `apt-get install python3-fastapi`) also blocks the Docker Hub registry.
  So: the daemon works, but no image — Neo4j or otherwise — can be pulled.
- No `neo4j`/`cypher-shell` binary exists as a system package, and no
  offline-installable Neo4j distribution (server tarball, `.deb`) is
  reachable for the same network-policy reason. Java 21 is present (in
  case a plain-jar install were possible), but there is nothing to fetch
  to install *with* it.
- No Python package (`neo4j`, or in fact `fastapi`/`sqlalchemy`/anything
  in `pyproject.toml`) could be installed in this container this session
  — `pip install`, `uv pip install -e .`, and the apt fallback all return
  403. This is the same restriction Phases 1–3 hit (ADR-005/006/008/013),
  not a new regression specific to Neo4j.

**Mac Desktop, via the device bridge (`mcp__remote-devices__device_bash`,
which runs in an isolated Linux VM on the user's Mac — explicitly **not**
a shell on macOS itself, so this does not prove anything about the Mac's
own Docker Desktop or Homebrew state):**
- No `docker` binary in that VM.
- Python 3.10 only (Phase 4, like the rest of the backend, targets 3.12
  language features — PEP 695 generics, `enum.StrEnum` usage patterns —
  so even a same-version pip install wouldn't produce a matching runtime).
- `curl` to `pypi.org` returns `403 Forbidden from proxy after CONNECT` —
  the VM's own egress is blocked by the same class of policy.

**Conclusion:** Neo4j could not be run for real, anywhere reachable from
this session, this phase. This is a genuine, actively-attempted gap, not
an assumed one.

**What was verified for real instead, given that constraint:**
- `ruff format --check` / `ruff check` — clean on every Phase 4 file
  (ruff itself is a standalone Rust binary already present at
  `/root/.local/bin/ruff`, so it needed no install).
- `python3.12 -m py_compile` on every new/changed file — clean (proves
  syntax validity under the actual target Python version, even without
  the dependencies installed to run it).
- `mypy` — fails immediately on `pyproject.toml`'s `pydantic.mypy` plugin
  (`No module named 'pydantic'`), identical to every prior phase's
  documented mypy gap; not a new Phase 4-specific failure.
- **The deterministic BFS traversal, cycle handling, tenant isolation, and
  relationship-validation logic — the actual business logic this phase's
  spec cares most about proving — genuinely ran, this session, for real.**
  `pytest` itself could not run (not installed, see above), so this was
  executed as a standalone `asyncio`-driven script
  (`/tmp/verify_phase4_pure_logic.py`, not committed — a manual run, not a
  replacement for the real `pytest` suite) that imports the actual
  `app.services.blast_radius.BlastRadiusService` and
  `app.domain.relationship_rules` modules directly and exercises them
  against `FakeGraphRepository` (`tests/fakes.py`). This was possible at
  all only because `app/graph/repository.py`'s `neo4j` import was made
  lazy (moved under `TYPE_CHECKING`/inside the methods that actually touch
  the driver, not at module level — see its module docstring) specifically
  so the `GraphRepository` Protocol and everything built on it could be
  imported without the `neo4j` package installed. Result: **26/26 checks
  passed**, covering every allowed relationship triple, the
  Model-cannot-call-Workflow rejection, a leaf component's empty blast
  radius, an unsynced-component error, direct vs. transitive dependents
  with correct depth/path values, `max_depth` cutoff, a 3-node cycle
  (A→B→C→A) terminating with no duplicates and the correct 2-member
  result (not 3 — confirming the cycle didn't leak the start node back
  into its own result), cross-tenant isolation, and deterministic ordering
  across repeated calls. This is real execution of real code, not a
  fabricated result — but it is not the same as running the actual
  `tests/test_blast_radius_service.py`/`test_relationship_rules.py` files
  through `pytest` (which additionally need `pytest`/`pytest-asyncio`
  installed, and were written to mirror this exact coverage plus more —
  see ADR-018). `DependencyGraphService`'s tests additionally need
  SQLAlchemy for the real-Postgres `sync_component` integration test, so
  that one genuinely could not be executed this way.
- `tests/test_graph_repository.py` exists specifically to exercise real
  Cypher against a real Neo4j instance, and is written to `pytest.skip()`
  cleanly (not fail, not fake a pass) when Neo4j isn't reachable — see
  its module docstring for the exact commands to run it for real.

**Action for the user (exact commands, once run somewhere with normal
network/Docker access):**
```
docker compose -f docker-compose.yml up -d neo4j
cd backend && make install
pytest tests/test_graph_repository.py -v          # real Cypher, currently skipped
pytest tests/ -v                                   # full suite, including the above
mypy app
```
Until that runs clean, Phase 4's Cypher itself (as opposed to the Python
logic layered on top of it) should be treated as reviewed, not proven.

## ADR-020 — Dependency direction convention: edges point from dependent to dependency (2026-09-13)

**Decision:** Every `DependencyRelationshipType` edge points **from the
component that depends on something, to the thing it depends on** — e.g.
`(Agent)-[:CALLS]->(Tool)`, `(Agent)-[:USES_MODEL]->(Model)`,
`(Workflow)-[:CONTAINS]->(Agent)`. "X's dependencies" = X's outgoing
edges. "X's dependents" (who breaks if X changes — the actual
blast-radius question) = X's **incoming** edges.

**Why this is worth an ADR of its own, not just a docstring:** it is the
single easiest thing to get backwards in this whole phase, and getting it
backwards would silently invert every blast-radius answer (reporting "what
this component depends on" when asked "what depends on this component," or
vice versa) without ever raising an error. `app/graph/repository.py`'s
`_LIST_DEPENDENCIES_QUERY` (follows `-[r]->`) and
`_LIST_DEPENDENTS_QUERY` (follows `<-[r]-`) are the only two Cypher
queries that read in opposite directions, and both carry an inline
comment restating this convention next to the arrow. `BlastRadiusService`
calls only `list_direct_dependents` (incoming edges), never
`list_direct_dependencies`, and this is tested explicitly (see
`test_blast_radius_service.py::test_direct_dependents_only` and
`::test_transitive_dependents_multiple_hops`, which assert the *specific*
components returned, not just a count, so a direction bug would fail
loudly).

**Alternative considered:** edges pointing from dependency to dependent
(`(Tool)-[:CALLED_BY]->(Agent)`) — rejected because relationship names
read more naturally in the "X USES_MODEL Y" / "X CALLS Y" direction that
matches how a developer would say the relationship out loud, at the cost
of "dependents" being the less-intuitive (incoming) direction — a cost
paid once, in this ADR and the code comments, rather than in every
relationship type's name.

## ADR-019 — Tenant isolation enforced directly in Cypher, not only at the application layer (2026-09-13)

**Decision:** Every Cypher query in `app/graph/repository.py` that reads
or writes a node includes `project_id` as a `MATCH` predicate on *every*
node pattern in the query — not just the "entry point" node. E.g.
`_LIST_DEPENDENCIES_QUERY` filters both the source (`{component_id: ...,
project_id: ...}`) and the target (`WHERE target.project_id = $project_id`)
by tenant, and `create_dependency`/`delete_dependency` scope both
`source`/`target` `MATCH` clauses by `project_id`.

**Why not rely on component IDs being UUIDs (globally unique, so
"scoping" is theoretically redundant):** the spec explicitly calls this
out as insufficient, and it's right to: a UUID being globally unique
doesn't stop a Cypher query written without a `project_id` filter from
matching (and returning, or worse, linking) a node that happens to belong
to a different tenant if that node's `component_id` were ever guessed,
logged, or reused across a bug. Scoping every `MATCH` closes that off
structurally — a cross-tenant query has no path to succeed even if the
caller supplies a correct-but-foreign `component_id`, rather than "isn't
expected to happen because IDs don't collide."

**Verified by:** `test_dependency_graph_service.py::
test_tenant_isolation_across_projects` and
`test_blast_radius_service.py::test_tenant_isolation_in_blast_radius`
both create a real edge under `project_a` and assert that querying the
*same* `component_id` under `project_b` raises `GraphComponentNotFound`
rather than leaking the other tenant's data — plus
`test_graph_repository.py::test_get_component_node_is_tenant_scoped`
against real Neo4j (skipped in this session per ADR-021, but written to
run for real once Neo4j is reachable).

## ADR-018 — Blast radius as pure-Python BFS over one-hop repository calls, not a Cypher variable-length path (2026-09-13)

**Decision:** `BlastRadiusService.compute()` is a plain Python
breadth-first search: it calls `GraphRepository.list_direct_dependents()`
one hop at a time, tracks a `visited` set of component IDs, and stops at
`max_depth`. It does **not** issue a single Cypher query like `MATCH
(x)<-[*1..10]-(y) RETURN y`.

**Why:** Three reasons, in order of how much they mattered:
1. **Cycle/dedup/depth-limit control is explicit and independently
   testable.** A Cypher variable-length path *can* be made cycle-safe
   (`apoc.path.subgraphNodes`, or manual dedup in the query), but that
   correctness then lives inside a query string that can only be tested
   against a live database. The BFS's cycle handling
   (`visited.add(component_id)` before a node is enqueued, so a cycle
   simply produces no new work at that node) is ~5 lines of plain Python,
   directly unit-tested via `FakeGraphRepository` — including the
   specific case the spec calls out, a 3-node cycle A→B→C→A
   (`test_blast_radius_service.py::test_cycle_terminates_and_deduplicates`)
   — without needing a real Neo4j instance at all. Given this phase's
   documented Neo4j-unavailability (ADR-021), that testability is not a
   nice-to-have; it is the difference between this algorithm having real
   test coverage and having none.
2. **No LLM, no heuristics, nothing implicit.** The spec is explicit that
   blast radius must be deterministic graph reachability. A hand-written
   BFS makes every step of "how did we decide X is affected" traceable in
   plain Python (and in each `BlastRadiusEntry.path`), rather than trusting
   a query planner's traversal order.
3. **`GraphRepository` stays a narrow, boring interface** (seven single-hop
   methods) instead of growing a bespoke "give me the whole reachable
   subgraph" method whose semantics (depth limit? cycle handling? which
   fields come back?) would have to be re-specified and re-tested per
   backend.

**Tradeoff being made:** N+1-shaped traversal (one query per BFS layer,
not one query for the whole subgraph) — for a project's scale (component
counts, not raw event volume) this is the right trade; if it ever isn't,
the `GraphRepository` Protocol boundary is exactly where a batched Cypher
`list_dependents_multi(ids)` method could be added later without
`BlastRadiusService`'s algorithm changing.

**Alternative considered:** `apoc.path.subgraphAll`/variable-length Cypher
— rejected per the above, and additionally requires the APOC plugin
(already planned for `docker-compose.yml`'s Neo4j service per Phase 1, but
an extra moving part this phase's core logic doesn't need to depend on).

## ADR-017 — Synchronous, service-driven Postgres→Neo4j sync (not event-driven) (2026-09-13)

**Decision:** `DependencyGraphService.sync_component()` is a plain async
method an API caller invokes explicitly (`POST
/projects/{id}/components/{id}/graph/sync`) to push one component's
current Postgres identity into Neo4j. There is no background worker, no
outbox table, no Kafka producer/consumer keeping the two databases
continuously in sync.

**Why:** The spec explicitly scopes Kafka/event-driven processing to
Phase 13, and building an event pipeline now would mean designing it twice
— once without the event bus that Phase 13 actually introduces (topics,
consumer groups, delivery semantics), and once for real. A synchronous
sync call is the honest amount of infrastructure for what Phase 4 alone
needs: a caller (a future API consumer, or Phase 5's compatibility engine)
that has just created/updated a component and wants it reflected in the
graph can call `sync_component` right after, and get a definite
success/failure answer inline rather than an eventually-consistent one.

**Consequence documented, not hidden:** the graph is only ever as fresh as
the last explicit `sync_component` call for a given component — creating
a `ComponentVersion` in Postgres does **not** automatically update the
graph node's `version`/`checksum`. This is intentional scope, not an
oversight: automatic propagation is exactly the kind of "keep two stores
consistent on every write" problem Phase 13's event pipeline exists to
solve properly (outbox pattern, retries, ordering), and doing it
ad hoc here would be building a worse version of that early.

## ADR-016 — Pluggable readiness-check registry (`app/core/readiness.py`) (2026-09-13)

**Decision:** `/api/v1/ready` no longer hardcodes a single `database: bool`
field. `app/core/readiness.py` holds a `READINESS_CHECKS: dict[str,
Callable[[], Awaitable[bool]]]` registry (currently `database` and
`graph`); the endpoint runs every registered check and returns `{"status":
"ok"|"unavailable", "checks": {name: bool, ...}}`, 503 if any check fails.

**Why:** The spec calls for Neo4j readiness to extend, not replace or
special-case, the existing Postgres check, and to be designed so
Redis/Kafka (Phases 13+) can be added the same way. A dict of
zero-argument async callables is the minimum structure that achieves that
— adding a future check is a one-line addition to `READINESS_CHECKS`, not
a change to the endpoint function itself. `/health` (pure liveness) is
deliberately untouched by any of this — it still never calls an external
dependency.

**Breaking change acknowledged:** this changes `ReadinessResponse`'s shape
(`database: bool` → `checks: dict[str, bool]`); `tests/test_health.py` was
updated in the same commit, and this is called out explicitly rather than
silently changing a previously-documented response shape.

## ADR-015 — Graph nodes carry identity only, never the JSONB content payload (2026-09-13)

**Decision:** `ComponentNode` (the dataclass `Neo4jGraphRepository`
reads/writes) mirrors exactly the identity columns already on Postgres's
`components`/`component_versions` tables (`component_id`, `project_id`,
`organization_id`, `component_type`, `name`, `slug`, `version`,
`checksum`, `synced_at`) and nothing else — no `content` JSONB, no
`description`, no `status`.

**Why:** PostgreSQL is, and stays, the single source of truth for a
component's actual configuration/content (per ADR-009's generic
`components`/`component_versions` design). Neo4j's job is answering graph
questions — "what depends on this," "what breaks if this changes" — which
need identity and relationships, not the payload those relationships point
at. Duplicating `content` into Neo4j would mean every future
`ComponentVersion` write has to remember to re-sync it (a second place to
keep the immutability/versioning invariants ADR-011 already enforces once,
in Postgres), for a field the graph layer never actually queries by.

**Consequence:** a blast-radius or dependency-listing API response can
name and identify an affected component, but a caller who needs to know
*what changed about it* still goes to `GET
/projects/{id}/components/{id}/versions/latest` — which is the correct
system to ask, since that's where the immutable, checksummed truth lives.

## ADR-014 — Ten fixed relationship types, validated by a closed (source_type, relationship_type, target_type) allow-list (2026-09-13)

**Decision:** `DependencyRelationshipType` is a ten-member `StrEnum`
(`USES_MODEL`, `USES_PROMPT`, `CALLS`, `BELONGS_TO`, `USES_SCHEMA`,
`CALLS_API`, `CONTAINS`, `DEPENDS_ON`, `APPLIES_TO`, `PROVIDED_BY`), and
`app/domain/relationship_rules.py` holds a `frozenset` of exactly which
`(source ComponentType, relationship_type, target ComponentType)` triples
are semantically valid (e.g. `(AGENT, CALLS, TOOL)` is allowed;
`(MODEL, CALLS, WORKFLOW)` is not). `DependencyGraphService.
create_dependency` calls `validate_relationship()` before any Neo4j write
reaches the repository layer.

**Why centralized and closed, not open/extensible-by-string:** the spec
explicitly requires rejecting nonsensical relationships (its own example:
a Model can't CALL a Workflow), and requires this rule live in exactly one
tested place rather than being re-implemented per route or per service
method. A closed allow-list (rather than, say, "anything goes, reject only
an explicit denylist") also means adding an eleventh relationship type
later is a deliberate, reviewed addition to both the enum and the
allow-list — never an accidental new capability from a typo'd string
reaching Neo4j. `test_relationship_rules.py::
test_every_relationship_type_is_used_by_at_least_one_allowed_triple`
guards the enum and the allow-list from drifting apart in either
direction.

**Alternative considered:** validating shape with a lighter rule (e.g. "any
type may `DEPENDS_ON` any type, but the other nine are type-restricted") —
rejected as under-specified; the spec's own example needs a real per-triple
table, not a partial rule with exceptions.

## ADR-013 — Phase 3 network/Docker verification gap persists (2026-09-13)

**Context:** Same restriction as ADR-005/ADR-006, re-confirmed for Phase 3:
`pytest`/`mypy` against real deps and `alembic upgrade` could not be run.

**What was verified instead:** migrations 0001 and 0002 were hand-
transcribed into raw SQL and applied together against real Postgres 16
(`agentabi_test`), then every new behavior was exercised directly: unique
`(project_id, component_type, slug)`, same slug allowed under a different
`component_type`, `sequence` auto-incrementing per insert, unique
`(component_id, version)`, the immutability trigger rejecting a `content`
update while allowing a `metadata` update, and cascade delete removing a
component's versions. Ruff (format + lint) and `python -m py_compile`
passed clean on every new file.

**Action for the user:** same as ADR-005/ADR-006 — run `make install &&
make lint && make typecheck && make test && make migrate` in an
environment with normal PyPI/Docker access before treating Phase 3 as
fully proven.

## ADR-012 — Checksum: canonicalized-JSON SHA-256, computed from content only (2026-09-13)

**Decision:** `compute_checksum()` serializes the content dict with sorted
keys and compact separators (`json.dumps(..., sort_keys=True,
separators=(",", ":"))`), then SHA-256 hashes the UTF-8 bytes. Only the
validated `content` dict is hashed — never `id`, `created_at`, `sequence`,
or `metadata`.

**Why:** Determinism requires that key order (a Python dict iteration
detail, not semantic content) never changes the hash, and that volatile/
non-semantic fields never participate — two versions of *different*
components with identical `content` should (and, verified in testing, do)
hash identically, which is exactly the "did anything actually change"
signal later compatibility scans need.

**Alternative considered:** hashing the raw JSON string the client sent —
rejected because it would make the checksum depend on incidental
formatting (whitespace, key order) rather than semantic content, defeating
the purpose.

## ADR-011 — Version immutability enforced at both the service boundary and the database (2026-09-13)

**Decision:** `ComponentRegistryService` exposes no method to modify or
delete an existing `ComponentVersion`. Independently, a Postgres trigger
(`prevent_component_version_mutation`, created in migration `0002`) raises
an exception on any `UPDATE` that changes `content` or `checksum`.
`metadata` remains mutable (it's explicitly non-semantic — annotations,
not content).

**Why two layers:** The service-layer omission stops the 99% case (nobody
building on top of this API can accidentally or intentionally mutate a
version). The trigger stops the remaining case: a raw SQL migration, an
admin console, or a future service that talks to Postgres directly and
bypasses `ComponentRegistryService` entirely. The project's rule against
"faking" immutability through comments alone is exactly what this guards
against — verified by directly attempting the UPDATE in psql (see
Verification) and in `tests/test_component_registry_service.py`.

## ADR-010 — `sequence` (Postgres IDENTITY) for "latest version," not a `latest_version_id` pointer (2026-09-13)

**Decision:** `component_versions.sequence` is a `BIGINT GENERATED BY
DEFAULT AS IDENTITY` column, globally monotonic (not per-component), with
an index on `(component_id, sequence DESC)`. "Latest version of a
component" = `ORDER BY sequence DESC LIMIT 1`.

**Why not `created_at`:** Postgres `timestamptz` has microsecond
resolution, but two versions inserted in the same request/transaction (or
under high concurrency) could plausibly tie, making "latest" ambiguous.
`sequence` can't tie — it's assigned atomically by the database.

**Why not a `components.latest_version_id` FK:** That requires a circular
foreign-key relationship between `components` and `component_versions`
(each table needs the other to exist first), forcing the FK to be added
in a second migration step after both tables exist, plus a read-modify-
write on `components` for every new version (a write-amplifying,
race-condition-prone pattern for something a simple indexed query already
answers cheaply). The spec explicitly defers "active/production version"
pointer semantics to a later phase — this design doesn't block adding one
then, it just doesn't build it prematurely now.

## ADR-009 — Generic `components` + `component_versions`, not one table per component type (2026-09-13)

**Decision:** A single `components` table (identity: type, name, slug,
status, tenant scope) and a single `component_versions` table (immutable
content snapshot, JSONB `content` column), rather than
`prompts`/`models`/`tools`/... as separate tables.

**Why:** All ten component types share an identical lifecycle — register,
version, list, get-latest, deprecate — and every later phase that touches
components generically (Neo4j sync in Phase 4, compatibility scans in
Phase 5, blast-radius traversal) wants to query/iterate "all components in
a project" or "all versions of this component" without ten near-duplicate
code paths or a UNION across ten tables.

**Tradeoff being made:** Postgres can't enforce a `prompts.template
NOT NULL`-style column constraint on `content`, since `content` is JSONB
and its shape depends on `component_type`. That type safety is provided by
the application instead — `app/domain/component_content.py`'s per-type
Pydantic models with `extra="forbid"`, enforced in
`ComponentRegistryService.create_component_version` before anything is
persisted. This is a deliberate application/database responsibility split:
the database guarantees identity/versioning invariants (uniqueness, FKs,
immutability); the application guarantees content shape.

**Alternative considered:** a `components`/`component_versions` pair *plus*
ten type-specific tables joined 1:1 to `component_versions` (e.g.
`prompt_version_details`) for real column-level constraints — rejected for
this phase as premature normalization; nothing yet needs to `WHERE
prompt_version_details.template LIKE ...` at the SQL level, and it would
require a migration per component type instead of one.

## ADR-008 — Verify migrations by direct DDL execution, not `alembic upgrade` (2026-09-13)

**Context:** Same sandbox network restriction as ADR-005/ADR-006 — the
`alembic` package itself cannot be installed here, so `alembic upgrade
head` cannot be run in this session.

**Decision:** Hand-transcribed the initial migration's `upgrade()` into raw
SQL and ran it directly against a real local Postgres 16 (`agentabi_test`),
then exercised every constraint by hand (duplicate slug, duplicate
`(organization_id, slug)`, duplicate membership, cascade delete on
organization removal) before dropping the schema again. This proves the
DDL and constraints are correct Postgres, even though the Alembic tool
itself wasn't exercised.

**Why not skip verification entirely:** The project's rule against fake
functionality — "prove what can reasonably be proven" — is more strongly
served by real-but-partial DB verification than by no DB verification at
all.

**Residual risk:** A typo that makes the *hand-transcribed* SQL diverge
from what `op.create_table(...)` would actually emit would not be caught
by this method. Running `alembic upgrade head` for real (see ROADMAP.md)
is still required before Phase 2 is fully trusted.

## ADR-007 — organization_members as an explicit join table with a role column (2026-09-13)

**Decision:** Model the user↔organization relationship as its own mapped
entity (`OrganizationMember`: `organization_id`, `user_id`, `role`), not a
plain SQLAlchemy `secondary=` many-to-many table.

**Why:** The association already needs an attribute (`role`) beyond the
two foreign keys, and later phases (RBAC, audit events referencing "who
did this in which org") will want to reference a membership row directly.
A `secondary=` table can't carry extra columns or be referenced by ID.

**Alternative considered:** Put a single `role`/`organization_id` directly
on `User` — rejected because it silently assumes a user belongs to exactly
one organization, which contradicts the spec's multi-tenant model.

## ADR-001 — Kafka in KRaft mode, no Zookeeper (2026-09-13)

**Decision:** Use `bitnami/kafka` in KRaft (combined broker+controller) mode
in `docker-compose.yml`.

**Why:** Zookeeper is legacy for new Kafka deployments (deprecated as of
Kafka 3.x/4.0 direction); KRaft is simpler to run locally (one container
instead of two) and matches what a new deployment would use in 2026.

**Alternative considered:** `confluentinc/cp-kafka` + Zookeeper — more
"enterprise-familiar" but adds an extra container and legacy surface area
with no benefit for a portfolio project.

## ADR-002 — asyncpg driver + SQLAlchemy 2.0 async (2026-09-13)

**Decision:** `postgres_dsn` defaults to `postgresql+asyncpg://...`; the app
is async end-to-end (FastAPI async routes, SQLAlchemy 2.0 async engine in
Phase 2, async Neo4j driver in Phase 4).

**Why:** The pipeline (webhook → diff → graph traversal → replay → risk
scoring) is I/O-bound across Postgres, Neo4j, Redis, Kafka, and two LLM
providers — async lets those overlap instead of serializing on threads.

**Alternative considered:** Sync SQLAlchemy + threadpool (simpler mental
model, but fights FastAPI's async-native design and complicates the
eventual Kafka consumer workers).

## ADR-003 — structlog for structured logging (2026-09-13)

**Decision:** structlog configured to emit console-renderer logs locally,
JSON in staging/production, with correlation IDs threaded via contextvars.

**Why:** Native Python `logging` + manual JSON formatting works but structlog
gives contextvar-based request binding (needed for correlation IDs across
async code) and processor pipelines for free.

**Alternative considered:** stdlib `logging` + `python-json-logger` only —
kept as a dependency for the formatter but structlog owns the pipeline.

## ADR-004 — Settings via pydantic-settings, one Settings class (2026-09-13)

**Decision:** All configuration lives in `app/core/config.py::Settings`,
loaded from environment/`.env`, cached via `lru_cache`-wrapped
`get_settings()`.

**Why:** Single source of truth, type-validated at startup (fails fast on
bad config), easy to override in tests.

## ADR-006 — Phase 2 network/Docker verification gap persists (2026-09-13)

**Context:** Same sandbox restriction as ADR-005, re-confirmed for Phase 2:
`pypi.org`/`files.pythonhosted.org` return `403 host_not_allowed`,
`archive.ubuntu.com` (tried as a fallback for `python3-asyncpg`/
`python3-alembic`/a newer `python3-sqlalchemy`) also returns 403 on every
package fetch, no local wheel cache has the needed packages, and no Docker
daemon is running.

**What was different this phase:** PostgreSQL 16 is installed as a system
package in this sandbox (unlike the other infra services). It was started
locally (`service postgresql start`) with an `agentabi`/`agentabi_test`
database, making real Postgres available for verification even though the
Python driver stack (SQLAlchemy/asyncpg/Alembic) could not be installed —
see ADR-008 for how that was used.

**Action for the user:** same as ADR-005 — run `make install && make lint
&& make typecheck && make test` in an environment with normal PyPI/Docker
access before treating Phase 2 as fully proven.

## ADR-005 — Phase 1 network/Docker verification gap (2026-09-13)

**Context:** This development sandbox has no reachable PyPI (outbound egress
policy returns `403 host_not_allowed` for `pypi.org`/`files.pythonhosted.org`)
and no running Docker daemon. This is an environment restriction, not a
project decision.

**Impact:** Phase 1 could not run `pip install`, `pytest`, `mypy` against the
real dependency set, or `docker build` / `docker compose up` inside this
session. What *was* verified: `ruff format --check` / `ruff check` (clean),
`python -m py_compile` on every backend file (clean), and
`docker compose config` (schema-valid).

**Action for the user:** run `make install && make lint && make typecheck &&
make test` and `make infra-up` locally (or in an environment with normal
network/Docker access) before treating Phase 1 as fully proven. Documented
here rather than silently claimed as done, per the project's "no fake
functionality" rule.
