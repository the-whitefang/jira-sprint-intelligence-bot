"""SQLAlchemy models for identity, access control, and session tokens.

Corresponds to the ``users``, ``roles``, ``permissions``,
``role_permissions``, ``user_roles``, and ``refresh_tokens`` tables from
the MySQL schema designed earlier. Relationships use ``back_populates``
(not ``backref``) throughout — explicit on both sides, which is what
modern SQLAlchemy 2.0 typed models expect and what keeps IDE
type-checking working correctly in both directions of a relationship.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Role(Base, TimestampMixin):
    """A named role (``admin``, ``manager``, ``contributor``) granting a set of permissions."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    permissions: Mapped[list[Permission]] = relationship(
        secondary="role_permissions", back_populates="roles", lazy="selectin"
    )
    users: Mapped[list[User]] = relationship(secondary="user_roles", back_populates="roles")


class Permission(Base):
    """A fine-grained permission code (e.g. ``sprint:read``, ``report:generate``)."""

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    roles: Mapped[list[Role]] = relationship(secondary="role_permissions", back_populates="permissions")


class RolePermission(Base):
    """Junction table for the many-to-many between roles and permissions.

    No ORM-level relationships of its own — callers navigate via
    ``Role.permissions`` / ``Permission.roles``, which SQLAlchemy resolves
    through this table transparently via the ``secondary=`` argument on
    those relationships.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class User(Base, TimestampMixin):
    """An application account."""

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_jira_account_id", "jira_account_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    jira_account_id: Mapped[str | None] = mapped_column(String(255))
    """Soft link to a Jira user's account ID, not a foreign key — Jira
    accounts and app accounts are managed independently; see the
    `assignee_jira_id` note on `Ticket` in `modules/tickets/models.py`
    for the same pattern applied to ticket assignees."""
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles", back_populates="users", lazy="selectin"
    )
    """Many-to-many via `user_roles`. Important async-SQLAlchemy usage note:
    assigning roles at creation time works directly — e.g.
    `UserRepository.create(..., roles=[admin_role])` — but appending to
    `.roles` on an object that was only just constructed (never loaded via
    a query) will attempt a synchronous lazy-load, which raises
    `MissingGreenlet` under the async driver. To add/remove roles on an
    *existing* user, always re-fetch it first (e.g. via
    `get_by_id_or_raise`, which uses `session.get()` and — thanks to
    `lazy="selectin"` — eager-loads this collection as part of that same
    call), then mutate the returned instance."""
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class UserRole(Base):
    """Junction table for the many-to-many between users and roles."""

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RefreshToken(Base):
    """A hashed refresh token backing the auth flow designed earlier.

    Only the hash is ever stored — never the raw token — matching the
    authentication flow design: the raw value exists only transiently in
    the response sent to the client.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id_revoked", "user_id", "revoked"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
