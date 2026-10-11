"""Alembic environment for the CortexOps backend (async engines: asyncpg / aiosqlite)."""
from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import records  # noqa: E402,F401  (registers every table on Base.metadata)

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Arbitrary constant; serializes concurrent `alembic upgrade` runs (several replicas booting) on Postgres.
MIGRATION_LOCK_ID = 727_150_001


def database_url() -> str:
    return (
        config.attributes.get("database_url")
        or context.get_x_argument(as_dictionary=True).get("db_url")
        or get_settings().database_url
    )


def _configure(**kwargs) -> None:
    context.configure(target_metadata=target_metadata, compare_type=True, **kwargs)


def run_migrations_offline() -> None:
    url = database_url()
    _configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
