"""API key authentication for CortexOps backend.

Keys are stored hashed in the database.
Format: cxo-<random 32 hex chars>
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db

settings = get_settings()

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Lazy import to avoid circular dependency
_ApiKey = None


def _get_model():
    global _ApiKey
    if _ApiKey is None:
        from .models.records import ApiKey as _K
        _ApiKey = _K
    return _ApiKey


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, hashed_key).
    Store only the hash; return the raw key to the user once.
    """
    raw = f"cxo-{secrets.token_hex(32)}"
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_current_project(
    raw_key: str | None = Security(_api_key_header),
    db: AsyncSession = Depends(get_db),
) -> str:
    """FastAPI dependency. Returns the project name associated with the key."""
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Pass X-API-Key header.",
        )

    # Dev shortcut
    if settings.environment == "development" and raw_key == settings.internal_api_key:
        return "__dev__"

    ApiKey = _get_model()
    hashed = hash_key(raw_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.is_active == True)
    )
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )

    key_record.last_used_at = datetime.utcnow()
    await db.flush()

    return key_record.project


class OptionalAuth:
    """Use this when auth is optional (public endpoints, health check)."""
    async def __call__(
        self,
        raw_key: str | None = Security(_api_key_header),
        db: AsyncSession = Depends(get_db),
    ) -> str | None:
        if not raw_key:
            return None
        try:
            return await get_current_project(raw_key, db)
        except HTTPException:
            return None
