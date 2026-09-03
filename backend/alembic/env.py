"""Alembic migration environment.

Reads the database URL from the application's own ``Settings`` rather
than a hardcoded value in ``alembic.ini``, so there is exactly one source
of truth for the connection string. Imports
``app.db.import_models`` so autogenerate sees every table — importing
any single ``models.py`` here would only register that module's tables.

Runs migrations through the same async ``asyncmy`` engine machinery the
application itself uses, rather than requiring a second, sync-only MySQL
driver installed solely for migrations.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db import import_models  # noqa: F401  -- registers every model on Base.metadata
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Single source of truth for the DB URL: the app's own settings.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection (``alembic upgrade --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Configure Alembic against an already-open sync-facade connection and run migrations.

    Called via ``AsyncConnection.run_sync()`` — Alembic's migration
    runner is sync internally, so this bridges it onto the async
    connection the rest of the app uses.
    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live, async database connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
