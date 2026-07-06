"""API key authentication for CortexOps backend.

Keys are stored hashed in the database.
Format: cxo-<random 32 hex chars>
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db
from .tiers import TierInfo

settings = get_settings()

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)

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


async def _monthly_trace_count(db: AsyncSession, project: str) -> int:
    from .models.records import TraceRecord

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count_result = await db.execute(
        select(sa_func.count(TraceRecord.id)).where(
            TraceRecord.project == project,
            TraceRecord.created_at >= month_start,
        )
    )
    return count_result.scalar() or 0


async def _tier_from_jwt(credentials: HTTPAuthorizationCredentials, db: AsyncSession) -> TierInfo:
    from .routers.jwt_auth import _JWT_SECRET, _verify

    try:
        payload = _verify(credentials.credentials, _JWT_SECRET)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from exc

    project = payload.get("project") or payload.get("sub")
    if not project:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )

    key_id = payload.get("key_id") or ""
    tier = payload.get("tier", "free")
    scope = payload.get("scope", "read_write") or "read_write"

    if key_id:
        ApiKey = _get_model()
        result = await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.is_active)
        )
        key_record = result.scalar_one_or_none()
        if not key_record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has been revoked. Sign in again.",
            )
        tier = key_record.tier
        scope = getattr(key_record, "scope", "read_write") or "read_write"

    monthly_traces = await _monthly_trace_count(db, project)
    return TierInfo(
        project=project,
        tier=tier,
        key_id=key_id,
        monthly_traces=monthly_traces,
        scope=scope,
    )


async def get_current_key_info(
    raw_key: str | None = Security(_api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: AsyncSession = Depends(get_db),
) -> TierInfo:
    """
    FastAPI dependency. Returns TierInfo with project, tier, and monthly usage.
    Accepts either Authorization: Bearer <jwt> or X-API-Key: cxo-...
    """
    if credentials and credentials.credentials:
        return await _tier_from_jwt(credentials, db)

    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing credentials. Pass Authorization: Bearer <jwt> or X-API-Key header.",
        )

    # Dev shortcut — never honored in production
    if (
        not settings.is_production
        and settings.environment == "development"
        and raw_key
        and secrets.compare_digest(raw_key, settings.internal_api_key)
    ):
        return TierInfo(project="__dev__", tier="pro", key_id="dev")

    ApiKey = _get_model()
    hashed = hash_key(raw_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.is_active)
    )
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )

    # Expiry enforcement (checklist item — SLA & reliability)
    if key_record.expires_at and datetime.utcnow() > key_record.expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "key_expired",
                "message": f"API key expired at {key_record.expires_at.isoformat()}. Rotate or create a new key.",
                "expired_at": key_record.expires_at.isoformat(),
            },
        )

    key_record.last_used_at = datetime.utcnow()
    await db.flush()

    monthly_traces = await _monthly_trace_count(db, key_record.project)

    return TierInfo(
        project=key_record.project,
        tier=key_record.tier,
        key_id=key_record.id,
        monthly_traces=monthly_traces,
        scope=getattr(key_record, "scope", "read_write") or "read_write",
    )


async def get_current_project(
    raw_key: str | None = Security(_api_key_header),
    db: AsyncSession = Depends(get_db),
) -> str:
    """FastAPI dependency. Returns the project name. Backward-compatible."""
    info = await get_current_key_info(raw_key, db)
    return info.project


async def get_optional_key_info(
    raw_key: str | None = Security(_api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: AsyncSession = Depends(get_db),
) -> TierInfo | None:
    """Return TierInfo when credentials are valid; None when absent or invalid."""
    if not raw_key and not (credentials and credentials.credentials):
        return None
    try:
        return await get_current_key_info(raw_key, credentials, db)
    except HTTPException:
        return None


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