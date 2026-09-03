"""Generic repository base class implementing the Repository Pattern.

Every model-specific repository (``UserRepository``, ``SprintRepository``,
``TicketRepository``, ...) inherits from ``BaseRepository[ModelType]``
rather than reimplementing CRUD — this keeps data-access code uniform
across every module and lets service-layer code depend on a predictable
shape regardless of which model it's working with.

**Design note on the "Repository Pattern" being a concrete generic class,
not an abstract interface**: the system has exactly one relational
backend (MySQL via SQLAlchemy) with no plan to swap it, so interface-
segregating every repository behind a formal ``Protocol`` would mostly
add ceremony without a corresponding benefit — the usual reason for that
extra layer (swapping persistence technology under test) is already
covered by running the same repositories against SQLite in tests, which
needs no interface at all. If a genuine need for a swappable persistence
layer shows up later, promoting these method signatures to a
``Protocol`` in this same file is a small, additive change, not a rewrite.

**Transaction ownership**: methods here call ``session.flush()``, never
``session.commit()``. Flushing pushes pending changes to the database —
assigning autoincrement primary keys, triggering constraint checks —
without ending the transaction. Committing is a decision that belongs to
whoever owns the unit of work (``get_db()``'s request-scoped commit, or
``session_scope()`` for non-request code), not to an individual
repository call. This is what lets a service compose multiple repository
calls — e.g. "create a ticket, then write its first history row" — into
one atomic transaction: both share the same session, and either both
commit or both roll back together.
"""

from __future__ import annotations

import logging
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnExpressionArgument

from app.core.exceptions import ConflictException, DatabaseException, NotFoundException
from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)

logger = logging.getLogger(__name__)


class BaseRepository(Generic[ModelType]):
    """Generic async CRUD repository for a single SQLAlchemy model.

    Args:
        session: The unit-of-work-scoped ``AsyncSession`` this repository
            operates within — typically injected via ``Depends(get_db)``.
        model: The ORM model class this repository manages.
    """

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self._session = session
        self._model = model

    async def create(self, **values: Any) -> ModelType:
        """Create and flush a new row.

        Args:
            **values: Column values for the new row.

        Raises:
            ConflictException: A unique constraint was violated (e.g. a
                duplicate email or duplicate Jira key).
            DatabaseException: Any other database-level failure.
        """
        instance = self._model(**values)
        self._session.add(instance)
        await self._flush()
        return instance

    async def get_by_id(self, entity_id: Any) -> ModelType | None:
        """Fetch by primary key, or ``None`` if no such row exists."""
        return await self._session.get(self._model, entity_id)

    async def get_by_id_or_raise(self, entity_id: Any) -> ModelType:
        """Fetch by primary key.

        Raises:
            NotFoundException: No row exists with that primary key.
        """
        instance = await self.get_by_id(entity_id)
        if instance is None:
            raise NotFoundException(
                f"{self._model.__name__} with id={entity_id!r} not found",
                error_code=f"{self._model.__name__.upper()}_NOT_FOUND",
            )
        return instance

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        order_by: ColumnExpressionArgument[Any] | None = None,
    ) -> list[ModelType]:
        """List rows with offset/limit pagination.

        Args:
            offset: Rows to skip.
            limit: Maximum rows to return.
            order_by: An ORM column/expression to order by, e.g.
                ``User.created_at.desc()``. Left unordered if omitted —
                callers needing a stable page order across requests
                should always pass one, since an unordered result set's
                row order is not guaranteed to stay consistent between
                queries.
        """
        stmt = select(self._model).offset(offset).limit(limit)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Total row count for this model, ignoring any filtering."""
        result = await self._session.execute(select(func.count()).select_from(self._model))
        return int(result.scalar_one())

    async def update(self, instance: ModelType, **values: Any) -> ModelType:
        """Apply attribute updates to an already-loaded instance and flush.

        Takes a loaded instance rather than an id so callers that already
        have the row in hand (e.g. after ``get_by_id_or_raise`` plus a
        permission check) don't pay for a second fetch.

        Raises:
            ConflictException: The update violates a unique constraint.
            DatabaseException: Any other database-level failure.
        """
        for field, value in values.items():
            setattr(instance, field, value)
        await self._flush()
        return instance

    async def delete(self, instance: ModelType) -> None:
        """Delete an already-loaded instance and flush.

        Raises:
            ConflictException: The delete violates a foreign key
                constraint (a related row still references this one and
                the relationship isn't configured to cascade).
            DatabaseException: Any other database-level failure.
        """
        await self._session.delete(instance)
        await self._flush()

    async def _flush(self) -> None:
        """Flush pending changes, translating SQLAlchemy errors into domain exceptions.

        A flush failure leaves the session unusable until rolled back —
        this is a hard SQLAlchemy requirement, not a stylistic choice —
        so every error path here rolls back before raising. When several
        repository calls share one session as part of a larger unit of
        work, this means a failure partway through correctly undoes the
        earlier, not-yet-committed calls too: that's the atomic
        transaction behavior the caller expects, not a bug.
        """
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            logger.warning(
                "integrity_error",
                extra={"model": self._model.__name__},
                exc_info=True,
            )
            raise ConflictException(
                f"{self._model.__name__} violates a uniqueness or foreign key constraint",
                error_code=f"{self._model.__name__.upper()}_CONFLICT",
                details={"reason": str(exc.orig) if exc.orig else str(exc)},
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.error(
                "database_error",
                extra={"model": self._model.__name__},
                exc_info=True,
            )
            raise DatabaseException(
                f"Database operation failed for {self._model.__name__}"
            ) from exc
