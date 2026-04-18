"""
Admin endpoints — internal use only.
All endpoints require INTERNAL_API_KEY header.
Never expose these to end users.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.records import ApiKey, Project

router = APIRouter(prefix="/v1/admin", tags=["admin"])

_INTERNAL_KEY = os.getenv("INTERNAL_API_KEY", "dev_internal_key")


# ── Internal auth ─────────────────────────────────────────────────────────
def require_admin(x_internal_key: str | None = Header(None, alias="X-Internal-Key")) -> None:
    """Require INTERNAL_API_KEY header — blocks all non-admin access."""
    if not x_internal_key or x_internal_key != _INTERNAL_KEY:
        raise HTTPException(
            status_code=401,
            detail="X-Internal-Key header required. This endpoint is for admin use only.",
        )


# ── Schemas ───────────────────────────────────────────────────────────────
class AdminKeyResponse(BaseModel):
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


class UpgradeTierRequest(BaseModel):
    tier: str       # "free" | "pro"
    scope: str = "read_write"


class RevokeRequest(BaseModel):
    reason: str = "admin_revoke"


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/keys", response_model=list[AdminKeyResponse])
async def admin_list_all_keys(
    project: str | None = None,
    tier: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    List all API keys across all projects.
    Optionally filter by project or tier.

    Admin only — requires X-Internal-Key header.
    """
    q = select(ApiKey).order_by(ApiKey.created_at.desc()).limit(limit)
    if project:
        q = q.where(ApiKey.project == project)
    if tier:
        q = q.where(ApiKey.tier == tier)

    result = await db.execute(q)
    keys = result.scalars().all()

    return [
        AdminKeyResponse(
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


@router.post("/keys/{key_id}/revoke", status_code=200)
async def admin_revoke_key(
    key_id: str,
    body: RevokeRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    Revoke any API key by ID. No project ownership check — admin can revoke any key.
    Use this instead of raw SQL in Railway.

    Admin only — requires X-Internal-Key header.
    """
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(403, "Forbidden")

    key.is_active = False
    await db.commit()

    return {
        "revoked": True,
        "key_id": key_id,
        "project": key.project,
        "reason": body.reason,
    }


@router.post("/keys/{key_id}/upgrade", status_code=200)
async def admin_upgrade_key(
    key_id: str,
    body: UpgradeTierRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    Upgrade or downgrade a key's tier and scope.
    Use this to manually set a key to Pro after Stripe payment confirmation.

    Admin only — requires X-Internal-Key header.

    Example:
        POST /v1/admin/keys/{id}/upgrade
        X-Internal-Key: your-internal-key
        {"tier": "pro", "scope": "read_write"}
    """
    if body.tier not in ("free", "pro"):
        raise HTTPException(400, "tier must be 'free' or 'pro'")
    if body.scope not in ("read_write", "read_only"):
        raise HTTPException(400, "scope must be 'read_write' or 'read_only'")

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(403, "Forbidden")

    old_tier = key.tier
    key.tier  = body.tier

    # Set scope if column exists
    try:
        key.scope = body.scope
    except AttributeError:
        pass

    await db.commit()

    return {
        "upgraded": True,
        "key_id": key_id,
        "project": key.project,
        "old_tier": old_tier,
        "new_tier": body.tier,
        "scope": body.scope,
    }


@router.get("/projects", status_code=200)
async def admin_list_projects(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """List all projects and their key counts. Admin only."""
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc()).limit(limit)
    )
    projects = result.scalars().all()

    out = []
    for p in projects:
        keys_result = await db.execute(
            select(ApiKey).where(ApiKey.project == p.name, ApiKey.is_active)
        )
        active_keys = len(keys_result.scalars().all())
        out.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "created_at": p.created_at.isoformat(),
            "active_keys": active_keys,
        })

    return {"projects": out, "total": len(out)}


@router.post("/keys/{key_id}/scope", status_code=200)
async def admin_set_scope(
    key_id: str,
    scope: str,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    Set a key's scope without changing tier.
    Use to create read-only keys for dashboards or third-party integrations.

    Admin only — requires X-Internal-Key header.
    """
    if scope not in ("read_write", "read_only"):
        raise HTTPException(400, "scope must be 'read_write' or 'read_only'")

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(403, "Forbidden")

    try:
        key.scope = scope
    except AttributeError:
        raise HTTPException(500, "scope column not in DB — run migration first")

    await db.commit()

    return {"key_id": key_id, "project": key.project, "scope": scope}
