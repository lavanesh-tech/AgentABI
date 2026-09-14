"""Wires `GitHubOAuthService` for routes (Security Phase B). The only
place production `RedisOAuthStateStore`/`HttpxGitHubOAuthClient`
instances get constructed — routes depend on the service, never on
these concrete implementations."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oauth_state import RedisOAuthStateStore
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.redis import get_redis_client
from app.domain.exceptions import GitHubOAuthNotConfigured
from app.github.oauth_client import HttpxGitHubOAuthClient
from app.services.github_oauth_service import GitHubOAuthService


async def get_github_oauth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitHubOAuthService:
    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise GitHubOAuthNotConfigured()

    state_store = RedisOAuthStateStore(get_redis_client(settings))
    github_client = HttpxGitHubOAuthClient(
        client_id=settings.github_oauth_client_id,
        client_secret=settings.github_oauth_client_secret,
    )
    return GitHubOAuthService(
        session, settings=settings, state_store=state_store, github_client=github_client
    )
