from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_key_info
from ..db import get_db
from ..models.records import TraceRecord, Project
from ..models.schemas import TraceDetailResponse, TraceIngest, TraceResponse
from ..security import redact_pii, idempotency_store
from ..tiers import TierInfo, check_trace_quota, require_scope

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/traces", tags=["traces"])


@router.post("", response_model=TraceResponse, status_code=201, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def ingest_trace(
    body: TraceIngest,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """
    Ingest a trace from the SDK.

    Free tier: 5,000 traces/month max. Returns 429 when exceeded.
    Pro tier:  unlimited.
    PII redaction applied before storage.
    Idempotency: pass Idempotency-Key header to prevent duplicates on retry.
    """
    t0 = time.perf_counter()

    # ── Scope enforcement — read_only keys cannot ingest traces ───────────
    require_scope(tier_info, "read_write")

    # ── Idempotency check ─────────────────────────────────────────────────
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key, "POST:/v1/traces")
        if cached:
            return cached

    # ── Quota enforcement (free tier) ─────────────────────────────────────
    check_trace_quota(tier_info)

    # ── Auto-create project ───────────────────────────────────────────────
    result = await db.execute(select(Project).where(Project.name == body.project))
    if not result.scalar_one_or_none():
        db.add(Project(name=body.project))
        await db.flush()

    # ── Payload size bomb protection ─────────────────────────────────────
    raw_size = len(json.dumps(body.model_dump(), default=str))
    if raw_size > 131072:  # 128KB hard limit per trace
        raise HTTPException(
            status_code=413,
            detail=f"Payload too large ({raw_size} bytes). Max 128KB per trace."
        )

    # ── PII redaction before storage ──────────────────────────────────────
    safe_payload = body.model_dump()
    safe_payload["input"]  = redact_pii(safe_payload.get("input", {}))   # redact PII from inputs too
    safe_payload["output"] = redact_pii(safe_payload.get("output", {}))
    safe_payload["nodes"]  = redact_pii(safe_payload.get("nodes", []))
    if safe_payload.get("failure_detail"):
        safe_payload["failure_detail"] = redact_pii(safe_payload["failure_detail"])

    trace = TraceRecord(
        id=str(uuid.uuid4()),
        project=body.project,
        case_id=body.case_id,
        status=body.status,
        total_latency_ms=body.total_latency_ms,
        failure_kind=body.failure_kind,
        failure_detail=safe_payload.get("failure_detail"),
        environment=body.environment,
        raw_trace=json.dumps(safe_payload),
    )
    db.add(trace)
    await db.flush()
    await db.refresh(trace)

    response = TraceResponse(
        trace_id=trace.id,
        project=trace.project,
        case_id=trace.case_id,
        status=trace.status,
        total_latency_ms=trace.total_latency_ms,
        failure_kind=trace.failure_kind,
        failure_detail=trace.failure_detail,
        environment=trace.environment,
        created_at=trace.created_at,
    )

    if idempotency_key:
        idempotency_store.set(idempotency_key, "POST:/v1/traces", response)

    # Add tier info to response headers so SDK can display helpful warnings
    logger.debug(
        "op=ingest_trace duration_ms=%.2f project=%s tier=%s monthly=%d",
        (time.perf_counter() - t0) * 1000,
        body.project,
        tier_info.tier,
        tier_info.monthly_traces,
    )
    return response


@router.get("", response_model=list[TraceResponse], responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def list_traces(
    project: str = Query(...),
    limit: int = Query(50, le=500),
    status: str | None = Query(None),
    environment: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """
    List traces for a project.
    Free tier: only sees last 7 days. Pro: 90 days.
    """
    from datetime import datetime, timedelta

    retention_days = tier_info.retention_days
    # DB column is TIMESTAMP WITHOUT TIME ZONE — use naive UTC datetime
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    q = (
        select(TraceRecord)
        .where(TraceRecord.project == project)
        .where(TraceRecord.created_at >= cutoff)
    )
    if status:
        q = q.where(TraceRecord.status == status)
    if environment:
        q = q.where(TraceRecord.environment == environment)
    q = q.order_by(TraceRecord.created_at.desc()).limit(limit)

    result = await db.execute(q)
    traces = result.scalars().all()
    return [
        TraceResponse(
            trace_id=t.id,
            project=t.project,
            case_id=t.case_id,
            status=t.status,
            total_latency_ms=t.total_latency_ms,
            failure_kind=t.failure_kind,
            failure_detail=t.failure_detail,
            environment=t.environment,
            created_at=t.created_at,
        )
        for t in traces
    ]


@router.get("/quota", tags=["traces"], responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def get_quota(
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """Return current usage and limits for the authenticated project."""
    return {
        "project": tier_info.project,
        "tier": tier_info.tier,
        "monthly_traces": {
            "used": tier_info.monthly_traces,
            "limit": tier_info.trace_limit,
            "unlimited": tier_info.is_pro,
            "percent_used": (
                round(tier_info.monthly_traces / tier_info.trace_limit * 100, 1)
                if tier_info.trace_limit else 0
            ),
        },
        "retention_days": tier_info.retention_days,
        "features": {
            "slack_alerts":     tier_info.is_pro,
            "llm_judge":        tier_info.is_pro,
            "prompt_versioning":tier_info.is_pro,
            "unlimited_traces": tier_info.is_pro,
        },
        "upgrade_url": "https://getcortexops.com/#pricing" if tier_info.is_free else None,
    }


@router.get("/{trace_id}", response_model=TraceDetailResponse, responses={
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    429: {"description": "Rate limit exceeded"},
    500: {"description": "Internal server error"},
})
async def get_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """Get a single trace with full node waterfall."""
    result = await db.execute(select(TraceRecord).where(TraceRecord.id == trace_id))
    trace = result.scalar_one_or_none()
    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")

    return TraceDetailResponse(
        trace_id=trace.id,
        project=trace.project,
        case_id=trace.case_id,
        status=trace.status,
        total_latency_ms=trace.total_latency_ms,
        failure_kind=trace.failure_kind,
        failure_detail=trace.failure_detail,
        environment=trace.environment,
        created_at=trace.created_at,
        raw_trace=json.loads(trace.raw_trace),
    )
