"""Repositories for identity and access-control models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import RefreshToken, Role, User
from app.shared.base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    """Data access for user accounts."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        """Fetch a user by email — the login lookup path."""
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class RoleRepository(BaseRepository[Role]):
    """Data access for roles."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Role)

    async def get_by_name(self, name: str) -> Role | None:
        """Fetch a role by its unique name (e.g. ``"admin"``)."""
        stmt = select(Role).where(Role.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Data access for refresh tokens."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshToken)

    async def get_active_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Fetch a non-revoked, non-expired token by its hash.

        This is the refresh-flow lookup: the incoming refresh token is
        hashed by the caller, then matched against stored hashes here —
        the raw token itself is never persisted or compared directly.
        """
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_all_for_user(self, user_id: int) -> int:
        """Revoke every active token for a user.

        Used on password change or admin-initiated account deactivation
        — invalidates every session the user currently holds in one
        operation, rather than requiring each device to independently
        expire.

        Returns:
            The number of tokens revoked.
        """
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)
        )
        result = await self._session.execute(stmt)
        tokens = list(result.scalars().all())
        for token in tokens:
            token.revoked = True
        await self._flush()
        return len(tokens)
