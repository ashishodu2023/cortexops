"""Persistent audit trail for authentication and key lifecycle events."""
from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from .models.records import AuthAuditLog

_log = logging.getLogger(__name__)

Outcome = Literal["success", "failure"]


async def record_auth_event(
    db: AsyncSession,
    *,
    event: str,
    outcome: Outcome,
    project: str | None = None,
    key_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    detail: str | None = None,
) -> None:
    """Append an auth audit row. Never pass secrets (raw keys, JWTs, internal keys)."""
    safe_detail = (detail or "")[:500] or None
    safe_ua = (user_agent or "")[:512] or None
    safe_ip = (ip_address or "")[:64] or None

    db.add(
        AuthAuditLog(
            event=event,
            outcome=outcome,
            project=project,
            key_id=key_id,
            ip_address=safe_ip,
            user_agent=safe_ua,
            detail=safe_detail,
        )
    )
    await db.flush()

    _log.info(
        "auth_audit event=%s outcome=%s project=%s key_id=%s ip=%s detail=%s",
        event,
        outcome,
        project or "-",
        key_id or "-",
        safe_ip or "-",
        safe_detail or "-",
    )
