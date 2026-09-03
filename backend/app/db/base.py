"""SQLAlchemy declarative base and shared model conventions.

Every ORM model in the codebase inherits from :class:`Base` defined
here. This is the single object Alembic's autogenerate compares against
the live database — anything not registered on ``Base.metadata`` is
invisible to migrations (see ``app/db/import_models.py`` for how every
model module gets registered before that comparison happens).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# A fixed naming convention for every constraint/index SQLAlchemy creates
# implicitly (unique constraints, foreign keys, primary keys, indexes).
# Without this, SQLAlchemy and MySQL each generate their own arbitrary
# names, which makes `alembic revision --autogenerate` produce noisy,
# unstable diffs across machines and runs — pinning the convention is
# what keeps generated migrations deterministic and reviewable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in the application."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds ``created_at``/``updated_at`` columns with database-side defaults.

    ``updated_at`` uses ``onupdate`` so every UPDATE statement refreshes
    it automatically at the database level — no service or repository
    method has to remember to set it, and it stays correct even for
    updates issued outside this codebase entirely (a manual SQL fix, a
    future admin tool hitting the DB directly).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
