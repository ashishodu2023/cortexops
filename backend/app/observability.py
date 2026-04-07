"""
Observability depth — checklist item 4.
- Structured JSON logging with request context
- Token usage tracking
- Performance timing decorators
- Health metrics aggregation
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Callable

from pythonjsonlogger import jsonlogger


# ── Structured JSON logging ────────────────────────────────────────────────
def configure_logging(environment: str = "development") -> None:
    """Configure structured JSON logging for production."""
    handler = logging.StreamHandler()

    if environment == "production":
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        handler.setFormatter(formatter)
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    else:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    # Suppress noisy libs in production
    if environment == "production":
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ── Performance timing decorator (checklist item 4) ───────────────────────
def timed(operation_name: str | None = None):
    """Decorator to log execution time of async functions."""
    def decorator(func: Callable) -> Callable:
        name = operation_name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.debug("op=%s duration_ms=%.2f status=ok", name, elapsed_ms)
                return result
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.warning("op=%s duration_ms=%.2f status=error error=%s", name, elapsed_ms, exc)
                raise

        return wrapper
    return decorator


# ── Token usage tracker (checklist item 11 — cost monitoring) ─────────────
class TokenTracker:
    """
    Track LLM token usage per project and per request.
    In production this would write to a time-series store.
    """

    # Approximate cost per 1k tokens (USD) — update as pricing changes
    COST_PER_1K = {
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    }

    def __init__(self) -> None:
        self._usage: dict[str, dict] = {}

    def record(
        self,
        project: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        trace_id: str | None = None,
    ) -> dict:
        """Record token usage and return cost estimate."""
        pricing = self.COST_PER_1K.get(model, {"input": 0.005, "output": 0.015})
        cost_usd = (
            input_tokens / 1000 * pricing["input"]
            + output_tokens / 1000 * pricing["output"]
        )

        if project not in self._usage:
            self._usage[project] = {"total_tokens": 0, "total_cost_usd": 0.0, "calls": 0}

        self._usage[project]["total_tokens"] += input_tokens + output_tokens
        self._usage[project]["total_cost_usd"] += cost_usd
        self._usage[project]["calls"] += 1

        record = {
            "project": project,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost_usd, 6),
            "trace_id": trace_id,
        }

        logger.info("token_usage project=%s model=%s tokens=%d cost_usd=%.6f",
                    project, model, input_tokens + output_tokens, cost_usd)
        return record

    def get_project_usage(self, project: str) -> dict:
        return self._usage.get(project, {"total_tokens": 0, "total_cost_usd": 0.0, "calls": 0})


# ── Health aggregator (checklist item 4, 14) ──────────────────────────────
class HealthAggregator:
    """
    Collect health signals from across the system.
    Returned by GET /health in production.
    """

    def __init__(self) -> None:
        self._checks: dict[str, Callable] = {}

    def register(self, name: str, check: Callable) -> None:
        """Register an async health check function."""
        self._checks[name] = check

    async def run_all(self) -> dict:
        """Run all registered health checks and return aggregate status."""
        results = {}
        overall = "ok"

        for name, check in self._checks.items():
            try:
                start = time.perf_counter()
                await check()
                elapsed_ms = (time.perf_counter() - start) * 1000
                results[name] = {"status": "ok", "latency_ms": round(elapsed_ms, 2)}
            except Exception as exc:
                results[name] = {"status": "error", "error": str(exc)}
                overall = "degraded"

        return {"status": overall, "checks": results}


# Global instances
token_tracker = TokenTracker()
health_aggregator = HealthAggregator()
