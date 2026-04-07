"""
Retry, circuit breaker, and fault tolerance — checklist items 6, 14.
- Exponential backoff with jitter
- Circuit breaker for external services (Stripe, Slack, OpenAI)
- Partial failure handling
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Exponential backoff (checklist item 6) ────────────────────────────────
async def retry_with_backoff(
    func: Callable,
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> Any:
    """
    Retry an async callable with exponential backoff + jitter.

    Args:
        func: Async callable to retry.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        exceptions: Exception types that trigger a retry.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            # Full jitter: random value in [0, min(max_delay, base_delay * 2^attempt)]
            delay = min(max_delay, base_delay * (2 ** attempt))
            jitter = random.uniform(0, delay)
            logger.warning(
                "Attempt %d/%d failed for %s: %s. Retrying in %.2fs.",
                attempt + 1,
                max_retries,
                getattr(func, "__name__", str(func)),
                exc,
                jitter,
            )
            await asyncio.sleep(jitter)

    raise last_exc  # type: ignore[misc]


# ── Circuit breaker (checklist item 14) ───────────────────────────────────
class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal — requests pass through
    OPEN = "open"           # Failing — requests blocked immediately
    HALF_OPEN = "half_open" # Recovery probe — one request allowed


class CircuitBreaker:
    """
    Circuit breaker for external service calls (Stripe, Slack, OpenAI).

    State machine:
        CLOSED → OPEN  : failure_threshold consecutive failures
        OPEN → HALF_OPEN : after recovery_timeout seconds
        HALF_OPEN → CLOSED : success
        HALF_OPEN → OPEN   : failure
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if self._last_failure_time and (time.monotonic() - self._last_failure_time) > self.recovery_timeout:
                logger.info("Circuit %s entering HALF_OPEN for recovery probe.", self.name)
                self._state = CircuitState.HALF_OPEN
        return self._state

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError(f"Circuit '{self.name}' is OPEN. Service unavailable.")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit %s recovered — closing.", self.name)
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            if self._state != CircuitState.OPEN:
                logger.error(
                    "Circuit %s OPENED after %d failures.",
                    self.name,
                    self._failure_count,
                )
            self._state = CircuitState.OPEN

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
        }


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is in OPEN state."""


# ── Global circuit breakers for external services ─────────────────────────
stripe_circuit = CircuitBreaker(name="stripe", failure_threshold=3, recovery_timeout=60.0)
slack_circuit = CircuitBreaker(name="slack", failure_threshold=5, recovery_timeout=30.0)
openai_circuit = CircuitBreaker(name="openai", failure_threshold=5, recovery_timeout=45.0)


# ── Timeout wrapper (checklist item 2 — async safety) ─────────────────────
async def with_timeout(
    func: Callable,
    *args: Any,
    timeout_seconds: float = 30.0,
    fallback: Any = None,
    **kwargs: Any,
) -> Any:
    """
    Run an async callable with a timeout. Returns fallback on timeout instead
    of raising — prevents a slow external call from hanging the entire request.
    """
    try:
        return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(
            "Timeout after %.1fs calling %s. Returning fallback.",
            timeout_seconds,
            getattr(func, "__name__", str(func)),
        )
        return fallback


# ── Partial failure collector (checklist item 6) ──────────────────────────
class PartialResult:
    """
    Collect results and errors from multiple operations.
    Prevents one failing operation from aborting the batch.
    """

    def __init__(self) -> None:
        self.results: list[Any] = []
        self.errors: list[dict] = []

    def add_result(self, result: Any) -> None:
        self.results.append(result)

    def add_error(self, operation: str, error: Exception) -> None:
        self.errors.append({"operation": operation, "error": str(error), "type": type(error).__name__})
        logger.warning("Partial failure in %s: %s", operation, error)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def success_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict:
        return {
            "results": self.results,
            "errors": self.errors,
            "success_count": self.success_count,
            "error_count": len(self.errors),
        }
