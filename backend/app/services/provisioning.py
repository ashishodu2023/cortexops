"""Pro API key provisioning shared by the Stripe and PayPal webhooks."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_auth_event
from ..auth import generate_api_key
from ..db import retry_on_integrity_error
from ..models.records import ApiKey, Project
from .email import email_configured, pro_key_email, send_email

logger = logging.getLogger(__name__)

_PROVISION_ATTEMPTS = 3


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
    provision_ref: str | None = None,
) -> ProvisionResult:
    """Create a Pro key for `project` (idempotent per payment event and per project) and email it.

    Webhooks are retried by Stripe/PayPal and may reach several replicas at once. A delivery is a
    no-op when its `provision_ref` (default "<source>:<ref>") already minted a key, or when the
    project already has an active, unexpired Pro key. Concurrent deliveries are settled by the
    unique indexes on api_keys.provision_ref and on active provisioned Pro keys per project: the
    loser's insert fails, it rolls back and re-reads the winner's key.
    """
    provision_ref = (provision_ref or (f"{source}:{ref}" if ref else f"{source}:{uuid.uuid4()}"))[:255]

    async def _attempt() -> ProvisionResult | tuple[str, str]:
        existing = await db.scalar(select(ApiKey).where(ApiKey.provision_ref == provision_ref))
        if existing is None:
            existing = await db.scalar(
                select(ApiKey).where(
                    ApiKey.project == project,
                    ApiKey.tier == "pro",
                    ApiKey.is_active,
                    or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > datetime.utcnow()),
                )
            )
        if existing:
            logger.info("Pro key already exists for project=%s, skipping provision (source=%s)", project, source)
            return ProvisionResult(status="already_provisioned", key_id=existing.id)

        # Expired keys cannot authenticate; retire them so the one-active-provisioned-key index admits the new one.
        await db.execute(
            update(ApiKey)
            .where(
                ApiKey.project == project,
                ApiKey.tier == "pro",
                ApiKey.is_active,
                ApiKey.provision_ref.is_not(None),
                ApiKey.expires_at <= datetime.utcnow(),
            )
            .values(is_active=False)
        )
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
            provision_ref=provision_ref,
        )
        db.add(key)
        await record_auth_event(
            db, event="pro_key_provisioned", outcome="success", project=project, key_id=key.id,
            detail=f"source={source} ref={ref[:64]}",
        )
        await db.commit()
        return key.id, raw_key

    outcome = await retry_on_integrity_error(
        db, _attempt, attempts=_PROVISION_ATTEMPTS, what=f"pro key provisioning project={project}",
    )
    if isinstance(outcome, ProvisionResult):
        return outcome
    key_id, raw_key = outcome
    logger.info("Provisioned Pro key project=%s key_id=%s source=%s", project, key_id, source)

    email_status, provider = await deliver_pro_key(
        db, email=email, project=project, key_id=key_id, raw_key=raw_key,
    )
    await db.commit()
    return ProvisionResult(
        status="provisioned", key_id=key_id, email_status=email_status, email_provider=provider,
    )
