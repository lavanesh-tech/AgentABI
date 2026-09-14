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

    # --- PostgreSQL -----------------------------------------------------
    postgres_dsn: PostgresDsn = Field(
        default="postgresql+asyncpg://agentabi:agentabi@localhost:5432/agentabi"
    )

    # --- Redis ------------------------------------------------------------
    redis_dsn: RedisDsn = Field(default="redis://localhost:6379/0")

    # --- Neo4j --------------------------------------------------------------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "agentabi_dev_password"

    # --- Kafka --------------------------------------------------------------
    kafka_bootstrap_servers: str = "localhost:9092"

    # --- AI providers (never hardcode; empty means "not configured") ------
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # --- GitHub integration -------------------------------------------------
    github_webhook_secret: str | None = None
    github_app_id: str | None = None
    github_private_key: str | None = None

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

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance.

    lru_cache gives us a singleton without global mutable state: the first
    call constructs and validates Settings from the environment, every
    subsequent call (including in other modules) returns the same instance.
    Tests can bypass the cache with `get_settings.cache_clear()`.
    """

    return Settings()
