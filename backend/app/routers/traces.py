from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.records import TraceRecord, Project
from ..models.schemas import TraceDetailResponse, TraceIngest, TraceResponse
from ..security import redact_pii, idempotency_store

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/traces", tags=["traces"])


@router.post("", response_model=TraceResponse, status_code=201)
async def ingest_trace(
    body: TraceIngest,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    """
    Ingest a trace from the SDK.

    Idempotency: pass Idempotency-Key header to prevent duplicate traces on retry.
    PII redaction: output, nodes, and failure_detail are scrubbed before storage.
    """
    t0 = time.perf_counter()

    # Idempotency check (checklist item 6)
    if idempotency_key:
        cached = idempotency_store.get(idempotency_key, "POST:/v1/traces")
        if cached:
            return cached

    # Auto-create project if it doesn't exist
    result = await db.execute(select(Project).where(Project.name == body.project))
    project = result.scalar_one_or_none()
    if not project:
        project = Project(name=body.project)
        db.add(project)
        await db.flush()

    # PII redaction before storage (checklist item 7)
    safe_payload = body.model_dump()
    safe_payload["output"] = redact_pii(safe_payload.get("output", {}))
    safe_payload["nodes"] = redact_pii(safe_payload.get("nodes", []))
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

    # Cache for idempotency (checklist item 6)
    if idempotency_key:
        idempotency_store.set(idempotency_key, "POST:/v1/traces", response)

    logger.debug("op=ingest_trace duration_ms=%.2f project=%s", (time.perf_counter() - t0) * 1000, body.project)
    return response


@router.get("", response_model=list[TraceResponse])
async def list_traces(
    project: str = Query(...),
    limit: int = Query(50, le=500),
    status: str | None = Query(None),
    environment: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List traces for a project. Supports status and environment filters."""
    q = select(TraceRecord).where(TraceRecord.project == project)
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


@router.get("/{trace_id}", response_model=TraceDetailResponse)
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db)):
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