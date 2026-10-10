"""
Admin endpoints — internal use only.
All endpoints require INTERNAL_API_KEY header.
Never expose these to end users.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_auth_event
from ..auth import generate_api_key
from ..config import get_settings
from ..db import get_db
from ..models.records import ApiKey, AuthAuditLog, Project
from ..security import client_ip
from ..services.provisioning import deliver_pro_key, is_deliverable_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["admin"])
settings = get_settings()


# ── Internal auth ─────────────────────────────────────────────────────────
async def require_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_internal_key: str | None = Header(None, alias="X-Internal-Key"),
) -> None:
    """Require INTERNAL_API_KEY header — blocks all non-admin access."""
    expected = settings.internal_api_key
    ip = client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    if expected and x_internal_key and secrets.compare_digest(x_internal_key, expected):
        await record_auth_event(
            db, event="admin_access", outcome="success", ip_address=ip, user_agent=ua,
        )
        return
    await record_auth_event(
        db, event="admin_access", outcome="failure", ip_address=ip, user_agent=ua,
        detail="invalid_internal_key",
    )
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


class AuthAuditEntry(BaseModel):
    id: str
    event: str
    outcome: str
    project: str | None
    key_id: str | None
    ip_address: str | None
    user_agent: str | None
    detail: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/keys", response_model=list[AdminKeyResponse], responses={
    401: {"description": "Missing or invalid X-Internal-Key header"},
    403: {"description": "Forbidden"},
    500: {"description": "Internal server error"},
})
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


@router.post("/keys/{key_id}/revoke", status_code=200, responses={
    401: {"description": "Missing or invalid X-Internal-Key header"},
    403: {"description": "Forbidden"},
    500: {"description": "Internal server error"},
})
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


@router.post("/keys/{key_id}/upgrade", status_code=200, responses={
    401: {"description": "Missing or invalid X-Internal-Key header"},
    403: {"description": "Forbidden"},
    500: {"description": "Internal server error"},
})
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


class ResendKeyEmailRequest(BaseModel):
    email: str


@router.post("/keys/{key_id}/resend-email", status_code=200, responses={
    400: {"description": "Key revoked, expired, not Pro, or invalid email"},
    401: {"description": "Missing or invalid X-Internal-Key header"},
    403: {"description": "Forbidden"},
    409: {"description": "Key was rotated or revoked concurrently"},
    502: {"description": "Email delivery failed — key left unchanged"},
    500: {"description": "Internal server error"},
})
async def admin_resend_key_email(
    key_id: str,
    body: ResendKeyEmailRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """
    Rotate a Pro key and email the replacement to the customer.

    Raw keys are stored hashed, so a lost key email cannot be re-sent as-is.
    This revokes the old key and commits a new key with the same project/tier/scope
    before emailing it, so the customer is never sent a key the API does not know.
    If delivery fails, the old key is reactivated and the undelivered replacement
    revoked. The new key is never returned in the response.

    Admin only — requires X-Internal-Key header.
    """
    if not is_deliverable_email(body.email):
        raise HTTPException(400, "A valid email address is required")

    old_key = await db.scalar(select(ApiKey).where(ApiKey.id == key_id))
    if not old_key:
        raise HTTPException(403, "Forbidden")
    if not old_key.is_active:
        raise HTTPException(400, "Key is revoked — provision a new key instead")
    if old_key.tier != "pro":
        raise HTTPException(400, "Only Pro keys can be re-sent — rotate free keys with POST /v1/keys/{key_id}/rotate")
    if old_key.expires_at and old_key.expires_at <= datetime.utcnow():
        raise HTTPException(400, "Key is expired — provision a new key instead")

    project = old_key.project
    raw_key, hashed = generate_api_key()
    new_key = ApiKey(
        id=str(uuid.uuid4()),
        project=project,
        name=old_key.name,
        tier=old_key.tier,
        scope=getattr(old_key, "scope", "read_write") or "read_write",
        key_hash=hashed,
        expires_at=old_key.expires_at,
    )
    new_key_id = new_key.id

    # Conditional revoke: of two concurrent resends for the same key, only one matches a row.
    claimed = await db.execute(
        update(ApiKey).where(ApiKey.id == key_id, ApiKey.is_active).values(is_active=False)
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(409, f"Key {key_id} was rotated or revoked concurrently — nothing was sent")
    db.add(new_key)
    await db.commit()

    status, provider = await deliver_pro_key(
        db, email=body.email, project=project, key_id=new_key_id, raw_key=raw_key,
        event="pro_key_email_resend",
    )
    if status != "sent":
        await record_auth_event(
            db, event="pro_key_email_resend", outcome="failure", project=project, key_id=key_id,
            detail=f"status={status}",
        )
        try:
            await db.execute(update(ApiKey).where(ApiKey.id == new_key_id).values(is_active=False))
            await db.execute(update(ApiKey).where(ApiKey.id == key_id).values(is_active=True))
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            logger.exception(
                "RESEND_RESTORE_FAILED project=%s old_key_id=%s new_key_id=%s — "
                "retry with POST /v1/admin/keys/%s/resend-email",
                project, key_id, new_key_id, new_key_id,
            )
            raise HTTPException(
                500, f"Email delivery failed ({status}) and key {key_id} could not be restored — "
                     f"retry resend-email on key {new_key_id}",
            ) from None
        raise HTTPException(502, f"Email delivery failed ({status}) — key {key_id} left unchanged")

    try:
        await db.commit()
    except SQLAlchemyError:
        # Only the success audit row is lost; the rotation itself is already committed.
        await db.rollback()
        logger.exception("Audit commit failed after resend project=%s new_key_id=%s", project, new_key_id)
    return {
        "resent": True,
        "project": project,
        "old_key_id": key_id,
        "new_key_id": new_key_id,
        "provider": provider,
    }


@router.get("/projects", status_code=200, responses={
    401: {"description": "Missing or invalid X-Internal-Key header"},
    403: {"description": "Forbidden"},
    500: {"description": "Internal server error"},
})
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
        count_result = await db.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(ApiKey.project == p.name, ApiKey.is_active)
        )
        active_keys = count_result.scalar_one()
        out.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "created_at": p.created_at.isoformat(),
            "active_keys": active_keys,
        })
    return {"projects": out, "total": len(out)}


@router.post("/keys/{key_id}/scope", status_code=200, responses={
    401: {"description": "Missing or invalid X-Internal-Key header"},
    403: {"description": "Forbidden"},
    500: {"description": "Internal server error"},
})
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
    except AttributeError as exc:
        raise HTTPException(500, "scope column not in DB — run migration first") from exc

    await db.commit()

    return {"key_id": key_id, "project": key.project, "scope": scope}


@router.get("/auth-audit", response_model=list[AuthAuditEntry], responses={
    401: {"description": "Missing or invalid X-Internal-Key header"},
})
async def admin_list_auth_audit(
    project: str | None = Query(None),
    event: str | None = Query(None),
    outcome: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Full auth audit log across all projects. Admin only."""
    q = select(AuthAuditLog).order_by(AuthAuditLog.created_at.desc()).limit(limit)
    if project:
        q = q.where(AuthAuditLog.project == project)
    if event:
        q = q.where(AuthAuditLog.event == event)
    if outcome:
        q = q.where(AuthAuditLog.outcome == outcome)
    result = await db.execute(q)
    return list(result.scalars().all())
