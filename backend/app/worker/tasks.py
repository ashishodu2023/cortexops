from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from .celery_app import celery


@celery.task(bind=True, name="cortexops.run_eval")
def run_eval_task(
    self,
    run_id: str,
    project: str,
    dataset: dict,
    baseline_run_id: str | None = None,
    fail_on: str | None = None,
) -> dict:
    """Execute an eval run asynchronously.

    Updates the EvalRun record in the database with results.
    """
    return asyncio.get_event_loop().run_until_complete(
        _run_eval_async(self, run_id, project, dataset, baseline_run_id, fail_on)
    )


async def _run_eval_async(
    task,
    run_id: str,
    project: str,
    dataset: dict,
    baseline_run_id: str | None,
    fail_on: str | None,
) -> dict:
    from sqlalchemy import select
    from ..db import AsyncSessionLocal
    from ..models.records import CaseResultRecord, EvalRun

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(EvalRun).where(EvalRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return {"error": f"Run {run_id} not found"}

        run.status = "running"
        await db.commit()

    try:
        from cortexops import EvalSuite

        if "path" in dataset:
            ds = EvalSuite._load_dataset(dataset["path"])
        else:
            ds = EvalSuite._parse_dataset_dict(dataset)

        def noop_agent(inp: dict) -> dict:
            return {"output": f"[mock] received: {inp}"}

        summary = EvalSuite.run(dataset=ds, agent=noop_agent, verbose=False, fail_on=fail_on)

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(EvalRun).where(EvalRun.id == run_id))
            run = result.scalar_one_or_none()

            run.status = "completed"
            run.total_cases = summary.total_cases
            run.passed = summary.passed
            run.failed = summary.failed
            run.warnings = summary.warnings
            run.task_completion_rate = summary.task_completion_rate
            run.tool_accuracy = summary.tool_accuracy
            run.latency_p50_ms = summary.latency_p50_ms
            run.latency_p95_ms = summary.latency_p95_ms
            run.regressions = summary.regressions
            run.completed_at = datetime.now(timezone.utc)
            run.raw_summary = json.dumps(summary.model_dump(mode="json"))

            for cr in summary.case_results:
                db.add(CaseResultRecord(
                    run_id=run_id,
                    case_id=cr.case_id,
                    passed=cr.passed,
                    score=cr.score,
                    task_completion=cr.task_completion,
                    tool_accuracy=cr.tool_accuracy,
                    latency_ms=cr.latency_ms,
                    failure_kind=cr.failure_kind.value if cr.failure_kind else None,
                    failure_detail=cr.failure_detail,
                ))

            await db.commit()

        return {"run_id": run_id, "status": "completed", "passed": summary.passed, "failed": summary.failed}

    except Exception as exc:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(EvalRun).where(EvalRun.id == run_id))
            run = result.scalar_one_or_none()
            if run:
                run.status = "failed"
                run.error_detail = str(exc)
                run.completed_at = datetime.now(timezone.utc)
                await db.commit()
        raise
