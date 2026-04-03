from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.records import CaseResultRecord, EvalRun, Project
from ..models.schemas import (
    EvalDiffResponse,
    EvalRunRequest,
    EvalRunResponse,
    EvalSummaryResponse,
    CaseResultResponse,
)
from ..worker.tasks import run_eval_task

router = APIRouter(prefix="/v1/evals", tags=["evaluations"])


async def _ensure_project(db: AsyncSession, name: str) -> Project:
    result = await db.execute(select(Project).where(Project.name == name))
    project = result.scalar_one_or_none()
    if not project:
        project = Project(name=name)
        db.add(project)
        await db.flush()
    return project


@router.post("", response_model=EvalRunResponse, status_code=202)
async def trigger_eval_run(
    body: EvalRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trigger an async eval run via Celery. Returns run_id immediately."""
    await _ensure_project(db, body.project)

    run = EvalRun(
        project=body.project,
        status="pending",
        baseline_run_id=body.baseline_run_id,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    task = run_eval_task.delay(
        run_id=run.id,
        project=body.project,
        dataset=body.dataset if isinstance(body.dataset, dict) else {"path": body.dataset},
        baseline_run_id=body.baseline_run_id,
        fail_on=body.fail_on,
    )

    return EvalRunResponse(
        run_id=run.id,
        project=body.project,
        status="pending",
        task_id=task.id,
        message="Eval run queued. Poll GET /v1/evals/{run_id} for results.",
    )


@router.get("", response_model=list[EvalSummaryResponse])
async def list_eval_runs(
    project: str = Query(...),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EvalRun)
        .where(EvalRun.project == project)
        .order_by(EvalRun.created_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    return [_run_to_response(r) for r in runs]


@router.get("/diff", response_model=EvalDiffResponse)
async def diff_runs(
    a: str = Query(...),
    b: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    run_a = await _get_run_or_404(db, a)
    run_b = await _get_run_or_404(db, b)

    cases_a = await db.execute(select(CaseResultRecord).where(CaseResultRecord.run_id == a))
    cases_b = await db.execute(select(CaseResultRecord).where(CaseResultRecord.run_id == b))

    map_a = {r.case_id: r for r in cases_a.scalars()}
    map_b = {r.case_id: r for r in cases_b.scalars()}

    regressions = [cid for cid in map_a if cid in map_b and map_b[cid].score < map_a[cid].score - 5]
    improvements = [cid for cid in map_a if cid in map_b and map_b[cid].score > map_a[cid].score + 5]

    return EvalDiffResponse(
        run_id_a=a,
        run_id_b=b,
        task_completion_delta=run_b.task_completion_rate - run_a.task_completion_rate,
        tool_accuracy_delta=run_b.tool_accuracy - run_a.tool_accuracy,
        latency_p95_delta_ms=run_b.latency_p95_ms - run_a.latency_p95_ms,
        regressions=regressions,
        improvements=improvements,
    )


@router.get("/{run_id}", response_model=EvalSummaryResponse)
async def get_eval_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await _get_run_or_404(db, run_id)
    return _run_to_response(run)


async def _get_run_or_404(db: AsyncSession, run_id: str) -> EvalRun:
    result = await db.execute(select(EvalRun).where(EvalRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Eval run {run_id} not found")
    return run


def _run_to_response(run: EvalRun) -> EvalSummaryResponse:
    case_results: list[CaseResultResponse] = []
    if hasattr(run, "case_results") and run.case_results:
        case_results = [
            CaseResultResponse(
                case_id=r.case_id,
                passed=r.passed,
                score=r.score,
                task_completion=r.task_completion,
                tool_accuracy=r.tool_accuracy,
                latency_ms=r.latency_ms,
                failure_kind=r.failure_kind,
                failure_detail=r.failure_detail,
            )
            for r in run.case_results
        ]

    return EvalSummaryResponse(
        run_id=run.id,
        project=run.project,
        status=run.status,
        dataset_version=run.dataset_version,
        total_cases=run.total_cases,
        passed=run.passed,
        failed=run.failed,
        warnings=run.warnings,
        task_completion_rate=run.task_completion_rate,
        tool_accuracy=run.tool_accuracy,
        latency_p50_ms=run.latency_p50_ms,
        latency_p95_ms=run.latency_p95_ms,
        regressions=run.regressions,
        baseline_run_id=run.baseline_run_id,
        case_results=case_results,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )
