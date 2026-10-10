from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_key_info
from ..db import get_db
from ..models.records import TraceRecord
from ..models.schemas import TraceDetailResponse, TraceIngest, TraceResponse
from ..security import idempotency_store
from ..services.trace_store import authorize_trace_write, persist_trace
from ..tiers import TierInfo, require_project_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/traces", tags=["traces"])

_PROMPT_FILTER_BATCH = 100


def _json_field_token(key: str, value: str) -> str:
    # raw_trace is written with json.dumps defaults, so a top-level field serializes as `"key": "value"`
    return f"{json.dumps(key)}: {json.dumps(value)}"


def _load_raw(t: TraceRecord) -> dict:
    try:
        raw = json.loads(t.raw_trace) if t.raw_trace else {}
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def _to_response(t: TraceRecord, raw: dict | None = None) -> TraceResponse:
    if raw is None:
        raw = _load_raw(t)
    meta = raw.get("metadata") or {}
    sampled = meta.get("sampled") if isinstance(meta, dict) else None
    return TraceResponse(
        trace_id=t.id,
        project=t.project,
        case_id=t.case_id,
        status=t.status,
        total_latency_ms=t.total_latency_ms,
        failure_kind=t.failure_kind,
        failure_detail=t.failure_detail,
        environment=t.environment,
        prompt_name=raw.get("prompt_name"),
        prompt_version=raw.get("prompt_version"),
        sampled=sampled if isinstance(sampled, bool) else None,
        created_at=t.created_at,
    )


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
    authorize_trace_write(tier_info, body.project)

    # ── Idempotency check ─────────────────────────────────────────────────
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key, "POST:/v1/traces")
        if cached:
            return cached

    # ── Quota, 128KB size limit, project auto-create, PII redaction ───────
    trace, safe_payload = await persist_trace(db, tier_info, body)

    response = _to_response(trace, safe_payload)

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
    prompt_name: str | None = Query(None, max_length=255),
    prompt_version: str | None = Query(None, max_length=64),
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_current_key_info),
):
    """
    List traces for a project.
    Free tier: only sees last 7 days. Pro: 90 days.
    Optional from/to (ISO 8601) narrow results within retention window.
    """
    require_project_access(tier_info, project)

    from datetime import datetime, timedelta

    retention_days = tier_info.retention_days
    # DB column is TIMESTAMP WITHOUT TIME ZONE — use naive UTC datetime
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    q = (
        select(TraceRecord)
        .where(TraceRecord.project == project)
        .where(TraceRecord.created_at >= cutoff)
    )
    if from_ is not None:
        effective_from = from_.replace(tzinfo=None) if from_.tzinfo else from_
        q = q.where(TraceRecord.created_at >= max(effective_from, cutoff))
    if to is not None:
        effective_to = to.replace(tzinfo=None) if to.tzinfo else to
        q = q.where(TraceRecord.created_at <= effective_to)
    if status:
        q = q.where(TraceRecord.status == status)
    if environment:
        q = q.where(TraceRecord.environment == environment)
    prompt_filters = {
        key: value
        for key, value in (("prompt_name", prompt_name), ("prompt_version", prompt_version))
        if value
    }
    # The substring match is only a prefilter: the same token can appear inside nested
    # input/output/metadata, so rows are re-checked against the parsed top-level fields.
    for key, value in prompt_filters.items():
        q = q.where(TraceRecord.raw_trace.contains(_json_field_token(key, value), autoescape=True))
    q = q.order_by(TraceRecord.created_at.desc(), TraceRecord.id.desc())

    if not prompt_filters:
        result = await db.execute(q.limit(limit))
        return [_to_response(t) for t in result.scalars().all()]

    matches: list[TraceResponse] = []
    batch_size = max(limit, _PROMPT_FILTER_BATCH)
    offset = 0
    while len(matches) < limit:
        rows = (await db.execute(q.offset(offset).limit(batch_size))).scalars().all()
        for t in rows:
            raw = _load_raw(t)
            if all(raw.get(key) == value for key, value in prompt_filters.items()):
                matches.append(_to_response(t, raw))
                if len(matches) == limit:
                    break
        if len(rows) < batch_size:
            break
        offset += batch_size
    return matches


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

    require_project_access(tier_info, trace.project)

    raw = json.loads(trace.raw_trace)
    return TraceDetailResponse(**_to_response(trace, raw).model_dump(), raw_trace=raw)
