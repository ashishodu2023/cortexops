"""Shared trace persistence used by every ingest path (SDK JSON and OTLP).

Keeps quota, the per-trace size limit and PII redaction identical across ingest
routes so a trace is stored the same way no matter how it arrived.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.records import Project, TraceRecord
from ..models.schemas import TraceIngest
from ..security import redact_pii
from ..tiers import TierInfo, check_trace_quota, require_project_access, require_scope

MAX_TRACE_BYTES = 131072  # 128KB hard limit per trace


def authorize_trace_write(tier_info: TierInfo, project: str) -> None:
    """read_only keys cannot ingest traces, and keys only write to their own project."""
    require_scope(tier_info, "read_write")
    require_project_access(tier_info, project)


def enforce_trace_size(payload: dict[str, Any]) -> None:
    raw_size = len(json.dumps(payload, default=str))
    if raw_size > MAX_TRACE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Payload too large ({raw_size} bytes). Max 128KB per trace.",
        )


def redact_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload)
    safe["input"] = redact_pii(safe.get("input", {}))
    safe["output"] = redact_pii(safe.get("output", {}))
    safe["nodes"] = redact_pii(safe.get("nodes", []))
    if safe.get("failure_detail"):
        safe["failure_detail"] = redact_pii(safe["failure_detail"])
    safe["metadata"] = redact_pii(safe.get("metadata", {}))
    safe["prompt_name"] = redact_pii(safe.get("prompt_name"))
    safe["prompt_version"] = redact_pii(safe.get("prompt_version"))
    return safe


async def ensure_project(db: AsyncSession, name: str) -> None:
    result = await db.execute(select(Project).where(Project.name == name))
    if not result.scalar_one_or_none():
        db.add(Project(name=name))
        await db.flush()


async def persist_trace(
    db: AsyncSession,
    tier_info: TierInfo,
    body: TraceIngest,
    *,
    existing: TraceRecord | None = None,
    record_id: str | None = None,
    redact: Callable[[dict[str, Any]], dict[str, Any]] = redact_trace_payload,
) -> tuple[TraceRecord, dict[str, Any]]:
    """Validate limits, redact and store a trace. Returns the record and the stored payload.

    Callers must run `authorize_trace_write` first. Updating an `existing` record does not
    count against the monthly quota because no new trace is created.
    """
    if existing is None:
        check_trace_quota(tier_info)

    payload = body.model_dump()
    enforce_trace_size(payload)
    await ensure_project(db, body.project)
    safe_payload = redact(payload)
    environment = body.environment or "development"

    if existing is not None:
        trace = existing
        trace.status = body.status
        trace.total_latency_ms = body.total_latency_ms
        trace.failure_kind = body.failure_kind
        trace.failure_detail = safe_payload.get("failure_detail")
        trace.environment = environment
        trace.raw_trace = json.dumps(safe_payload)
    else:
        trace = TraceRecord(
            id=record_id or str(uuid.uuid4()),
            project=body.project,
            case_id=body.case_id,
            status=body.status,
            total_latency_ms=body.total_latency_ms,
            failure_kind=body.failure_kind,
            failure_detail=safe_payload.get("failure_detail"),
            environment=environment,
            raw_trace=json.dumps(safe_payload),
        )
        db.add(trace)
    await db.flush()
    await db.refresh(trace)
    return trace, safe_payload
