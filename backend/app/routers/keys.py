from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta

from fastapi import Header, Query, APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import generate_api_key, get_current_key_info, get_optional_key_info
from ..config import get_settings
from ..db import get_db
from ..models.records import ApiKey, Project
from ..security import bootstrap_limiter, client_ip as resolve_client_ip
from ..tiers import TierInfo, require_scope

router = APIRouter(prefix="/v1/keys", tags=["api keys"])
settings = get_settings()

_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")


# ── Schemas ───────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    project: str
    name: str = "default"
    scope: str = "read_write"           # "read_write" | "read_only"
    expires_in_days: int | None = None  # None = never expires

    @field_validator("project")
    @classmethod
    def validate_project(cls, v: str) -> str:
        v = v.strip().lower()
        if not _PROJECT_RE.match(v):
            raise ValueError("project must be 3-64 chars: lowercase letters, numbers, hyphens, underscores")
        return v


class ApiKeyResponse(BaseModel):
    id: str
    project: str
    name: str
    tier: str
    scope: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyResponse):
    raw_key: str  # Shown exactly once — never retrievable again


class RotateResponse(BaseModel):
    new_key: str
    old_key_id: str
    new_key_id: str
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────

VALID_SCOPES = {"read_write", "read_only"}
_INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "")


async def _ensure_project(db: AsyncSession, name: str) -> None:
    result = await db.execute(select(Project).where(Project.name == name))
    if not result.scalar_one_or_none():
        db.add(Project(name=name))
        await db.flush()


async def _project_has_active_keys(db: AsyncSession, project: str) -> bool:
    result = await db.execute(
        select(func.count()).select_from(ApiKey).where(
            ApiKey.project == project,
            ApiKey.is_active,
        )
    )
    return (result.scalar() or 0) > 0


async def _issue_key(
    db: AsyncSession,
    body: ApiKeyCreate,
    *,
    tier: str = "free",
) -> ApiKeyCreateResponse:
    if body.scope not in VALID_SCOPES:
        raise HTTPException(400, f"scope must be one of: {', '.join(VALID_SCOPES)}")

    await _ensure_project(db, body.project)

    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)

    raw_key, hashed = generate_api_key()
    key = ApiKey(
        tier=tier,
        project=body.project,
        key_hash=hashed,
        name=body.name,
        scope=body.scope,
        expires_at=expires_at,
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)

    return ApiKeyCreateResponse(
        id=key.id,
        project=key.project,
        name=key.name,
        tier=key.tier,
        scope=key.scope,
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        raw_key=raw_key,
    )


def _has_internal_access(x_internal_key: str | None) -> bool:
    return bool(_INTERNAL_KEY and x_internal_key and secrets.compare_digest(x_internal_key, _INTERNAL_KEY))


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/bootstrap", response_model=ApiKeyCreateResponse, status_code=201, responses={
    409: {"description": "Project already has active keys"},
    429: {"description": "Rate limit exceeded"},
})
async def bootstrap_api_key(
    body: ApiKeyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Create the first free-tier API key for a new project.

    Rate-limited (5/hour per IP). Only works when the project has no active keys.
    Use POST /v1/keys with authentication to create additional keys in production.
    """
    client_ip = resolve_client_ip(request)
    if not bootstrap_limiter.is_allowed(client_ip):
        raise HTTPException(429, "Bootstrap rate limit exceeded. Try again later.")

    if await _project_has_active_keys(db, body.project):
        raise HTTPException(
            409,
            "Project already has active keys. Sign in and create keys from the dashboard, "
            "or use an authenticated POST /v1/keys request.",
        )

    return await _issue_key(db, body)


@router.post("", response_model=ApiKeyCreateResponse, status_code=201, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def create_api_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo | None = Depends(get_optional_key_info),
    x_internal_key: str | None = Header(None, alias="X-Internal-Key"),
):
    """
    Create a new API key. Raw key returned only once.

    Production: requires an authenticated read_write key for the same project,
    or X-Internal-Key (admin/billing). For first-time setup use POST /v1/keys/bootstrap.
    """
    if settings.environment == "production" and not _has_internal_access(x_internal_key):
        if not tier_info:
            raise HTTPException(
                401,
                "Authentication required. Use POST /v1/keys/bootstrap for your first key.",
            )
        require_scope(tier_info, "read_write")
        if tier_info.project != body.project and tier_info.project != "__dev__":
            raise HTTPException(403, "You can only create keys for your own project.")
    elif tier_info:
        require_scope(tier_info, "read_write")
        if tier_info.project != body.project and tier_info.project != "__dev__":
            raise HTTPException(403, "You can only create keys for your own project.")

    return await _issue_key(db, body)


@router.get("/{project}", response_model=list[ApiKeyResponse], responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def list_api_keys(
    project: str,
    limit: int = Query(100, ge=1, le=500, description="Max keys to return"),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """List all API keys for a project. Only shows keys for your own project."""
    if tier_info.project != project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only list keys for your own project.")

    q = select(ApiKey).where(ApiKey.project == project)
    if not include_inactive:
        q = q.where(ApiKey.is_active)
    q = q.order_by(ApiKey.created_at.desc())

    result = await db.execute(q)
    keys = result.scalars().all()

    return [
        ApiKeyResponse(
            id=k.id,
            project=k.project,
            name=k.name,
            tier=k.tier,
            scope=getattr(k, "scope", "read_write") or "read_write",
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
        )
        for k in keys
    ]


@router.post("/{key_id}/rotate", response_model=RotateResponse, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def rotate_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """
    Rotate an API key — revoke old key and issue new one with same tier/project.
    Old key is invalidated immediately. New key is shown once — store it immediately.
    """
    require_scope(tier_info, "read_write")
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    old_key = result.scalar_one_or_none()

    if not old_key:
        raise HTTPException(404, f"Key {key_id} not found.")

    if old_key.project != tier_info.project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only rotate keys in your own project.")

    if not old_key.is_active:
        raise HTTPException(400, "Key is already revoked. Create a new key instead.")

    raw_key, hashed = generate_api_key()
    new_key = ApiKey(
        tier=old_key.tier,
        project=old_key.project,
        key_hash=hashed,
        name=old_key.name,
        scope=getattr(old_key, "scope", "read_write") or "read_write",
        expires_at=old_key.expires_at,
    )
    db.add(new_key)

    old_key.is_active = False

    await db.flush()
    await db.refresh(new_key)
    await db.commit()

    return RotateResponse(
        new_key=raw_key,
        old_key_id=key_id,
        new_key_id=new_key.id,
        message=f"Rotated. Old key {key_id[:8]}... revoked. Store your new key — shown once only.",
    )


@router.delete("/{key_id}", status_code=204, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def revoke_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """Revoke a key immediately. All requests using it will receive 401."""
    require_scope(tier_info, "read_write")
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(404, f"Key {key_id} not found.")

    if key.project != tier_info.project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only revoke keys in your own project.")

    key.is_active = False
    await db.flush()
    await db.commit()


@router.get("/{key_id}/info", response_model=ApiKeyResponse, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def get_key_info(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """Get metadata for a key — tier, scope, expiry, last used timestamp."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(404, f"Key {key_id} not found.")

    if key.project != tier_info.project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only view keys in your own project.")

    return ApiKeyResponse(
        id=key.id,
        project=key.project,
        name=key.name,
        tier=key.tier,
        scope=getattr(key, "scope", "read_write") or "read_write",
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
    )
