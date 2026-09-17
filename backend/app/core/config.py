"""Centralized application configuration.

All runtime configuration is loaded from environment variables (or a local
.env file in development) through this single Settings object. Nothing in
the rest of the codebase should read os.environ directly — inject or import
`get_settings()` instead. This keeps configuration testable (override via
env vars or dependency override) and keeps secrets out of source code.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App identity -----------------------------------------------------
    app_name: str = "AgentABI"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    # --- API ----------------------------------------------------------------
    api_v1_prefix: str = "/api/v1"
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    # Credentials (cookies/Authorization headers) only matter with CORS when
    # a browser-based frontend needs them; kept True to match the frontend's
    # eventual use of the Bearer JWT from a browser — never paired with a
    # wildcard origin (app/core/cors.py asserts this at startup).
    cors_allow_credentials: bool = True

    # --- Request size protection (Security Phase D) ------------------------
    # Rejected before the body is fully read (app/core/request_size.py) —
    # 5MB comfortably covers every JSON payload this API accepts (trajectory
    # events, scan/replay requests) without inviting a large-body DoS.
    max_request_body_bytes: int = 5_000_000

    # --- Rate limiting (Security Phase D) -----------------------------------
    # Redis-backed fixed-window counters (app/core/rate_limit.py). Separate
    # limits per endpoint class, each independently configurable.
    rate_limit_auth_requests: int = 10
    rate_limit_auth_window_seconds: int = 60
    rate_limit_mutation_requests: int = 30
    rate_limit_mutation_window_seconds: int = 60
    rate_limit_scan_replay_requests: int = 10
    rate_limit_scan_replay_window_seconds: int = 60
    # First-organization onboarding (`POST /organizations`) is a rare,
    # one-time-per-user action — a tight, conservative limit (mirrors
    # rate_limit_auth_requests) is appropriate; it is not a bulk-creation
    # API and never will be (see OrganizationAlreadyProvisioned).
    rate_limit_onboarding_requests: int = 5
    rate_limit_onboarding_window_seconds: int = 60
    # Fail-closed is the single, non-configurable policy: if Redis can't
    # be reached to evaluate a limit, the request is denied (503) rather
    # than silently let through unchecked. See docs/DECISIONS.md — this
    # is deliberately not a per-endpoint toggle, to keep the policy easy
    # to audit.

    # --- Reverse-proxy trust (Security Phase D) -----------------------------
    # How many `X-Forwarded-For` entries (from the right) to trust as
    # having been added by a real proxy in front of this API, for deriving
    # a client identity to rate-limit anonymous requests by. 0 (default)
    # means "no proxy is trusted" — use the direct TCP peer address only,
    # correct for local dev and any deployment without a reverse proxy.
    # A production deployment behind exactly one trusted load balancer
    # (e.g. an ALB) should set this to 1. Never trust the full header
    # as-is: every entry left of the trusted proxies' own entries is
    # client-supplied and trivially spoofable.
    trusted_proxy_count: int = 0

    # --- PostgreSQL -----------------------------------------------------
    # Constructing PostgresDsn/RedisDsn directly (rather than passing a
    # plain `str` literal to `Field(default=...)`) gives the field a
    # default whose *static* type actually matches its annotation — a
    # bare string literal default is only a `PostgresDsn` once pydantic
    # validates it, which doesn't happen for unvalidated defaults, so
    # mypy correctly flagged the literal-string form as a real
    # `str`-vs-`PostgresDsn` mismatch. This also validates the local-dev
    # default DSN's format at import time instead of only on first
    # override.
    postgres_dsn: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://agentabi:agentabi@localhost:5432/agentabi")
    )

    # --- Redis ------------------------------------------------------------
    redis_dsn: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # --- Neo4j --------------------------------------------------------------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "agentabi_dev_password"

    # --- Kafka (Phase 13) ---------------------------------------------------
    # `kafka_enabled=False` (the default, and every local/unit-test default)
    # keeps the deterministic core fully usable without Kafka: Phase 12's PR
    # analysis runs inline on the webhook request exactly as it did before
    # this phase (spec §12). Flipping it on switches the webhook route to
    # enqueue an analysis-request event for `app.kafka.worker` instead.
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_client_id: str = "agentabi"
    # Stable, configurable group (spec §18) — never generated per-process —
    # so multiple worker processes horizontally scale by sharing partitions
    # of the same topics rather than each seeing every message.
    kafka_consumer_group: str = "agentabi-analysis-workers"
    kafka_analysis_request_topic: str = "agentabi.analysis.requests"
    kafka_analysis_result_topic: str = "agentabi.analysis.results"
    kafka_analysis_dlq_topic: str = "agentabi.analysis.dlq"
    kafka_enabled: bool = False

    # --- AI providers (never hardcode; empty means "not configured") ------
    # OpenAI-only for now (Phase 8) — Gemini stays defined but unused
    # (Phase 9 skipped, see docs/ROADMAP.md) so Settings doesn't need to
    # change shape if a Gemini/other provider is added later.
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # --- OpenAI explanation provider (Phase 8) -------------------------
    # gpt-4o-mini: cheap, fast, and structured-output-capable — this is a
    # text-summarization task over already-computed evidence, not a task
    # that needs a frontier reasoning model. Overridable per deployment;
    # never hardwired into business logic (only read here and passed
    # through to `OpenAIProvider` — see docs/DECISIONS.md).
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 30.0
    openai_max_retries: int = 2

    # --- GitHub integration -------------------------------------------------
    # `github_webhook_secret` (Security Phase E): environment-only, no
    # real value ships here or in .env.example — empty means "webhook
    # processing not configured" (`GitHubWebhookNotConfigured`, 503).
    # Never logged (app/trajectory/redaction.py's key set covers
    # `webhook_secret`), never serialized in any response model, and
    # compatible with a future AWS Secrets Manager-backed env value —
    # this field never changes shape, only where the environment gets
    # its value from.
    github_webhook_secret: str | None = None
    github_app_id: str | None = None
    github_private_key: str | None = None

    # `github_checks_token` (Phase 12): a pre-provisioned GitHub App
    # installation access token (or a fine-grained PAT with `checks:write`)
    # used to call the Checks API. A true GitHub-App-JWT installation-
    # token exchange needs RS256 (RSA) signing, which needs a crypto
    # dependency this sandbox cannot install (same PyPI-403 restriction
    # documented for every prior phase, and the exact reason
    # `app/auth/jwt.py` hand-rolls HS256 instead of using PyJWT) — so
    # Phase 12 reads a statically configured token via
    # `GitHubCredentialProvider` (app/github/checks_models.py), a Protocol
    # boundary a real `github_app_id`/`github_private_key`-based token
    # exchange can implement later without touching any caller. Empty
    # means "not configured" — `GitHubChecksClient` calls fail with
    # `GitHubAuthenticationFailed` rather than sending an empty token.
    github_checks_token: str | None = None

    # --- JWT authentication (Security Phase A) -------------------------------
    # No real secret ships here or in .env.example — only a local-dev
    # default so `local`/`test` work without setup. Production must set
    # JWT_SECRET via the environment (later, AWS Secrets Manager); nothing
    # in this codebase ever logs it (see `app/core/logging.py`'s field
    # allowlist — `jwt_secret` is deliberately not one of the bound
    # context fields anywhere).
    jwt_secret: str = "local-dev-only-insecure-secret-change-me"
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "agentabi"
    jwt_audience: str = "agentabi-api"
    jwt_access_token_expire_minutes: int = 60

    # --- GitHub OAuth2 login (Security Phase B) -------------------------
    # No real credentials ship here or in .env.example — empty defaults
    # mean "not configured" (mirrors openai_api_key/gemini_api_key
    # above), same as every provider secret in this file. Production
    # sources these from the environment (later, AWS Secrets Manager);
    # nothing in this codebase ever logs github_client_secret.
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    github_oauth_redirect_uri: str = "http://localhost:8000/api/v1/auth/github/callback"
    github_oauth_state_ttl_seconds: int = 600

    # --- OpenTelemetry (Phase 15) -----------------------------------------
    # Off by default (spec §5): AgentABI must run identically whether or
    # not a collector exists. Nothing here is a secret — OTLP endpoints
    # are infrastructure addresses, not credentials.
    otel_enabled: bool = False
    otel_service_name: str = "agentabi-api"
    otel_service_version: str = "0.1.0"
    # No production hostname hardcoded (spec §6) — local dev default only.
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_exporter_otlp_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    otel_traces_sampler: Literal["always_on", "always_off", "parentbased_traceidratio"] = (
        "parentbased_traceidratio"
    )
    otel_traces_sampler_arg: float = 1.0
    # Falls back to `environment` when unset — kept distinct so an
    # OTel-only environment label can differ without touching the
    # broader `environment` literal (e.g. a "staging-tracing-canary").
    otel_environment: str | None = None

    @property
    def otel_resource_environment(self) -> str:
        return self.otel_environment or self.environment

    # --- Prometheus metrics (Phase 16) -------------------------------------
    # On by default (spec §5) — unlike tracing, metrics are meant to be the
    # always-on operational signal; `/metrics` simply degrades to a
    # placeholder body if `prometheus_client` isn't installed (see
    # app/observability/metrics.py's render_metrics), so leaving this true
    # never breaks a deployment that hasn't set up Prometheus yet.
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    # Spec §14: the Kafka worker isn't a FastAPI process, so it can't serve
    # `/metrics` off the API's router — it opens this separate port via
    # `prometheus_client.start_http_server` instead when metrics are on.
    metrics_worker_port: int = 9101

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance.

    lru_cache gives us a singleton without global mutable state: the first
    call constructs and validates Settings from the environment, every
    subsequent call (including in other modules) returns the same instance.
    Tests can bypass the cache with `get_settings.cache_clear()`.
    """

    return Settings()
