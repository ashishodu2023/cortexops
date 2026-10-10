"""Pro API key provisioning shared by the Stripe and PayPal webhooks."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_auth_event
from ..auth import generate_api_key
from ..models.records import ApiKey, Project
from .email import email_configured, pro_key_email, send_email

logger = logging.getLogger(__name__)

_provision_lock = asyncio.Lock()


@dataclass
class ProvisionResult:
    status: str                    # "provisioned" | "already_provisioned"
    key_id: str
    email_status: str | None = None  # "sent" | "no_email_address" | "not_configured" | "failed"
    email_provider: str | None = None


def is_deliverable_email(email: str | None) -> bool:
    if not email:
        return False
    email = email.strip()
    return "@" in email and len(email) <= 254 and " " not in email


async def deliver_pro_key(
    db: AsyncSession,
    *,
    email: str | None,
    project: str,
    key_id: str,
    raw_key: str,
    event: str = "pro_key_email",
) -> tuple[str, str | None]:
    """Email a raw Pro key and audit the outcome. Returns (email_status, provider)."""
    if not is_deliverable_email(email):
        status, provider = "no_email_address", None
    elif not email_configured():
        status, provider = "not_configured", None
    else:
        subject, body = pro_key_email(project, raw_key)
        provider = await send_email(email.strip(), subject, body)
        status = "sent" if provider else "failed"

    await record_auth_event(
        db,
        event=event,
        outcome="success" if status == "sent" else "failure",
        project=project,
        key_id=key_id,
        detail=f"status={status}" + (f" provider={provider}" if provider else ""),
    )
    if status != "sent":
        logger.error(
            "PRO_KEY_EMAIL_UNDELIVERED project=%s key_id=%s status=%s — "
            "resend with POST /v1/admin/keys/%s/resend-email",
            project, key_id, status, key_id,
        )
    return status, provider


async def provision_pro_key(
    db: AsyncSession,
    *,
    project: str,
    email: str | None,
    source: str,
    ref: str,
) -> ProvisionResult:
    """Create a Pro key for `project` (idempotent per project) and email it to the customer.

    Webhooks are retried by Stripe/PayPal, so a second delivery for a project that
    already has an active, unexpired Pro key is a no-op.
    """
    # Serializes overlapping webhook deliveries within this process (the API runs as a
    # single replica). Cross-process safety needs a unique index on active Pro keys.
    async with _provision_lock:
        existing = await db.scalar(
            select(ApiKey).where(
                ApiKey.project == project,
                ApiKey.tier == "pro",
                ApiKey.is_active,
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > datetime.utcnow()),
            )
        )
        if existing:
            logger.info("Pro key already exists for project=%s — skipping provision (source=%s)", project, source)
            return ProvisionResult(status="already_provisioned", key_id=existing.id)

        if not await db.scalar(select(Project).where(Project.name == project)):
            db.add(Project(name=project, description=f"{source} {ref}"))
            await db.flush()

        raw_key, hashed = generate_api_key()
        key = ApiKey(
            id=str(uuid.uuid4()),
            project=project,
            name=f"{source}-pro-{ref[:12]}" if ref else f"{source}-pro",
            tier="pro",
            scope="read_write",
            key_hash=hashed,
            is_active=True,
        )
        db.add(key)
        await record_auth_event(
            db, event="pro_key_provisioned", outcome="success", project=project, key_id=key.id,
            detail=f"source={source} ref={ref[:64]}",
        )
        await db.commit()
    logger.info("Provisioned Pro key project=%s key_id=%s source=%s", project, key.id, source)

    email_status, provider = await deliver_pro_key(
        db, email=email, project=project, key_id=key.id, raw_key=raw_key,
    )
    await db.commit()
    return ProvisionResult(
        status="provisioned", key_id=key.id, email_status=email_status, email_provider=provider,
    )
