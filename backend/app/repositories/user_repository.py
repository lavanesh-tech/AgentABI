"""Persistence access for User. Thin, like every other repository in
this codebase — the authentication dependency (`app/api/deps/auth.py`)
owns the "does this user exist and is it active" decision, this module
only reads the row."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_github_id(self, github_user_id: int) -> User | None:
        """Look up a user by GitHub's immutable numeric id (Security
        Phase B) — never by `github_login`, which can change."""
        stmt = select(User).where(User.github_user_id == github_user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_from_github(
        self, *, email: str, github_user_id: int, github_login: str
    ) -> User:
        user = User(
            email=email,
            full_name=None,
            is_active=True,
            github_user_id=github_user_id,
            github_login=github_login,
        )
        self._session.add(user)
        await self._session.flush()
        return user
