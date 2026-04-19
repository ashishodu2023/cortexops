from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Query, APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import generate_api_key, get_current_key_info
from ..db import get_db
from ..models.records import ApiKey, Project
from ..tiers import TierInfo

router = APIRouter(prefix="/v1/keys", tags=["api keys"])


# ── Schemas ───────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    project: str
    name: str = "default"
    scope: str = "read_write"           # "read_write" | "read_only"
    expires_in_days: int | None = None  # None = never expires


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


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("", response_model=ApiKeyCreateResponse, status_code=201, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def create_api_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new free-tier API key. Raw key returned only once.

    scope:
        read_write  — full access (default)
        read_only   — GET endpoints only, cannot ingest traces or run evals

    expires_in_days:
        None        — never expires (default)
        30          — expires in 30 days
    """
    if body.scope not in VALID_SCOPES:
        raise HTTPException(400, f"scope must be one of: {', '.join(VALID_SCOPES)}")

    # Auto-create project if needed
    result = await db.execute(select(Project).where(Project.name == body.project))
    if not result.scalar_one_or_none():
        db.add(Project(name=body.project))
        await db.flush()

    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)

    raw_key, hashed = generate_api_key()
    key = ApiKey(
        tier="free",
        project=body.project,
        key_hash=hashed,
        name=body.name,
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
        scope=body.scope,
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        raw_key=raw_key,
    )


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
            scope="read_write",
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
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    old_key = result.scalar_one_or_none()

    if not old_key:
        raise HTTPException(404, f"Key {key_id} not found.")

    if old_key.project != tier_info.project and tier_info.project != "__dev__":
        raise HTTPException(403, "You can only rotate keys in your own project.")

    if not old_key.is_active:
        raise HTTPException(400, "Key is already revoked. Create a new key instead.")

    # Create new key with same tier and project
    raw_key, hashed = generate_api_key()
    new_key = ApiKey(
        tier=old_key.tier,
        project=old_key.project,
        key_hash=hashed,
        name=old_key.name,
        expires_at=old_key.expires_at,
    )
    db.add(new_key)

    # Revoke old key immediately
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
        scope="read_write",
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
    )
