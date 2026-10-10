from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import MetaData
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings

settings = get_settings()
_log = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Mirrors PostgreSQL's default constraint names so the Alembic baseline matches tables that
# production created with create_all() before migrations existed.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


async def init_db() -> None:
    """Prepare the schema at startup.

    RUN_MIGRATIONS=1: apply Alembic migrations (`alembic upgrade head`).
    SQLite without RUN_MIGRATIONS (local dev, tests): create_all().
    Anything else (Postgres): refuse to start unless the schema is already at the latest revision.
    """
    from . import migrate

    if settings.run_migrations:
        await migrate.upgrade_head_async()
        return
    if settings.is_sqlite:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return
    await migrate.assert_schema_current(engine)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


T = TypeVar("T")


async def retry_on_integrity_error(
    db: AsyncSession,
    attempt: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    what: str,
) -> T:
    """Run `attempt`, rolling back and re-running it when a unique constraint rejects its writes.

    `attempt` must re-read whatever state it depends on: the rollback discards everything the
    session did since its last commit. Re-raises the IntegrityError after `attempts` tries.
    """
    for n in range(1, attempts + 1):
        try:
            return await attempt()
        except IntegrityError:
            await db.rollback()
            if n == attempts:
                raise
            _log.info("Unique constraint conflict on %s (attempt %d/%d), retrying", what, n, attempts)
            await asyncio.sleep(random.uniform(0, 0.02 * n))  # jitter so colliding writers spread out
    raise AssertionError("unreachable")
