# Security Concepts — Interview Notes

Short explanations of the concepts used in Security Phases A–F, for
talking through this project in an interview.

**Authentication vs authorization.** Authentication answers "who are you?"
(here: GitHub OAuth2 + a JWT). Authorization answers "what are you allowed
to do?" (here: RBAC + tenant scoping).

**OAuth2.** A protocol for delegated login: AgentABI never sees the user's
GitHub password. The user authorizes AgentABI with GitHub directly, and
GitHub redirects back with a code AgentABI exchanges for identity info.

**JWT (JSON Web Token).** A signed, self-contained token AgentABI issues
after login. The server can verify it (signature) without a database
lookup, but AgentABI still reloads the *role* from the database every
request rather than trusting a role embedded in the token, because a role
in a token issued an hour ago could be stale.

**Issuer / audience / expiration.** Standard JWT claims: issuer (who
signed it), audience (who it's meant for), expiration (when it stops being
valid). Checking all three stops a token from one system, or an expired
token, being replayed against this API.

**RBAC (Role-Based Access Control).** Permissions are attached to roles
(OWNER/ADMIN/MEMBER), not individual users — simpler to reason about and
to change than per-user permission lists.

**Multi-tenant isolation.** Multiple organizations share one database;
every query is scoped by `organization_id`/`project_id` so one tenant can
never see another's data. Trying to access another tenant's resource
returns 404 (not 403) so its existence isn't even confirmed.

**Redis distributed rate limiting.** Limits requests per identity (user or
IP) using fixed time windows counted in Redis, which works correctly
across multiple API server instances (a per-process in-memory counter
wouldn't). Fails *closed*: if Redis is unreachable, requests are rejected
rather than let through unlimited.

**HMAC webhook verification.** GitHub can't hold an AgentABI JWT, so it
proves a webhook is really from GitHub by signing the raw request body
with a shared secret (HMAC-SHA256) and sending the signature in a header.
AgentABI recomputes the signature and compares it.

**Constant-time comparison.** Comparing the computed and received
signatures byte-by-byte with early exit lets an attacker learn how many
leading bytes matched by timing the response (a timing side channel). A
constant-time comparison takes the same time regardless, closing that
leak.

**Audit logging.** A separate, append-only record of security-relevant
events (logins, permission denials, webhook deliveries) — append-only so
no one, including an admin, can quietly edit history after the fact.

**Pydantic validation.** Every request body is parsed into a typed model;
invalid data is rejected before it reaches business logic. Response models
work the other way — they whitelist exactly which fields go out, so a
secret field on an internal object can't accidentally leak in an API
response.

**OpenAPI (Swagger).** A machine-readable description of the API, derived
automatically from the code (routes, models, security requirements) rather
than hand-maintained — it can't silently drift out of date the way a
hand-written doc can.

**Postman.** A GUI tool for manually exercising an API. A shared
"collection" (a set of pre-built requests) plus an "environment" (config
like base URL and tokens) lets anyone on the team exercise every endpoint
without writing code.

**Integration vs unit tests.** A unit test exercises one function in
isolation (e.g. "does the HMAC comparison correctly reject a modified
payload?"). An integration test exercises the whole stack — HTTP request
in, real dependencies, response out. This project's security logic is
unit-tested; integration tests exist but require dependencies (FastAPI,
SQLAlchemy, a real Postgres/Redis) not installable in this build
environment, so they're written and reviewed but not proven to pass here.
