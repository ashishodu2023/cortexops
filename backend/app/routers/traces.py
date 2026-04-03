from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.records import TraceRecord, Project
from ..models.schemas import TraceDetailResponse, TraceIngest, TraceResponse

router = APIRouter(prefix="/v1/traces", tags=["traces"])


@router.post("", response_model=TraceResponse, status_code=201)
async def ingest_trace(body: TraceIngest, db: AsyncSession = Depends(get_db)):
    """Ingest a trace from the SDK."""
    result = await db.execute(select(Project).where(Project.name == body.project))
    project = result.scalar_one_or_none()
    if not project:
        project = Project(name=body.project)
        db.add(project)
        await db.flush()

    trace = TraceRecord(
        id=str(uuid.uuid4()),
        project=body.project,
        case_id=body.case_id,
        status=body.status,
        total_latency_ms=body.total_latency_ms,
        failure_kind=body.failure_kind,
        failure_detail=body.failure_detail,
        environment=body.environment,
        raw_trace=json.dumps(body.model_dump()),
    )
    db.add(trace)
    await db.flush()
    await db.refresh(trace)

    return TraceResponse(
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


@router.get("", response_model=list[TraceResponse])
async def list_traces(
    project: str = Query(...),
    limit: int = Query(50, le=500),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(TraceRecord).where(TraceRecord.project == project)
    if status:
        q = q.where(TraceRecord.status == status)
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
