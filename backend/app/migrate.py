"""Programmatic Alembic entry points used at startup and by scripts/migrate.py."""
from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


class SchemaNotCurrentError(RuntimeError):
    pass


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if database_url:
        cfg.attributes["database_url"] = database_url
    return cfg


def head_revisions(cfg: Config | None = None) -> set[str]:
    return set(ScriptDirectory.from_config(cfg or alembic_config()).get_heads())


def upgrade_head(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")


async def upgrade_head_async(database_url: str | None = None) -> None:
    # env.py drives its own event loop, so it must not run on the caller's loop.
    await asyncio.to_thread(upgrade_head, database_url)


async def current_revisions(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        heads = await conn.run_sync(lambda sync_conn: MigrationContext.configure(sync_conn).get_current_heads())
    return set(heads)


async def assert_schema_current(engine: AsyncEngine) -> None:
    current, expected = await current_revisions(engine), head_revisions()
    if current != expected:
        raise SchemaNotCurrentError(
            f"Database schema is at revision {sorted(current) or 'none'}, the code expects {sorted(expected)}. "
            "Run `alembic upgrade head` from backend/ (or `python scripts/migrate.py`), or start with "
            "RUN_MIGRATIONS=1. Existing pre-Alembic databases: see docs/migrations.md."
        )
