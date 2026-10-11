"""Apply database migrations: `python scripts/migrate.py` (run from backend/, or /app in the image).

Intended as a deploy step (e.g. a Railway pre-deploy command). Exits non-zero on failure so
the deploy stops before new code runs against an old schema.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migrate import current_revisions, upgrade_head  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402


async def _current(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        return await current_revisions(engine)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", help="defaults to DATABASE_URL / app settings")
    args = parser.parse_args()

    from app.config import get_settings

    url = args.database_url or get_settings().database_url
    upgrade_head(url)
    print(f"Database at revision {', '.join(sorted(asyncio.run(_current(url))))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
