"""Fire Slack/webhook alerts after eval runs complete."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.records import ApiKey, CaseResultRecord, EvalRun
from .alerting import AlertPayload, send_eval_alerts

log = logging.getLogger(__name__)
settings = get_settings()


async def _project_is_pro(db: AsyncSession, project: str) -> bool:
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.project == project,
            ApiKey.is_active,
            ApiKey.tier == "pro",
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


def _failed_cases_from_results(case_results: list[CaseResultRecord]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for cr in case_results:
        if cr.passed:
            continue
        failed.append({
            "case_id": cr.case_id,
            "failure_kind": cr.failure_kind or "unknown",
            "score": cr.score or 0,
        })
    return failed


async def maybe_send_eval_alerts(
    db: AsyncSession,
    run: EvalRun,
    *,
    case_results: list[CaseResultRecord] | None = None,
) -> None:
    """Send configured alerts when a run completes. Pro projects only."""
    if run.status != "completed":
        return
    if not await _project_is_pro(db, run.project):
        return

    if case_results is None:
        result = await db.execute(
            select(CaseResultRecord).where(CaseResultRecord.run_id == run.id)
        )
        case_results = list(result.scalars().all())

    payload = AlertPayload(
        project=run.project,
        run_id=run.id,
        task_completion_rate=run.task_completion_rate or 0.0,
        tool_accuracy=run.tool_accuracy or 0.0,
        passed=run.passed or 0,
        failed=run.failed or 0,
        total_cases=run.total_cases or 0,
        regressions=run.regressions or 0,
        failed_cases=_failed_cases_from_results(case_results),
        environment=settings.environment,
    )

    try:
        results = send_eval_alerts(payload)
        if any(results.values()):
            log.info("Eval alerts sent for run %s: %s", run.id, results)
    except Exception:
        log.exception("Failed to send eval alerts for run %s", run.id)
