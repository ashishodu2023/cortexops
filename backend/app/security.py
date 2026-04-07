"""
Security hardening — checklist items 7, 3, 6.
- PII redaction before trace storage
- Request ID middleware for traceability
- Rate limiting via token bucket
- Idempotency key support
"""
from __future__ import annotations

import hashlib
import re
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


# ── PII redaction patterns (checklist item 7) ─────────────────────────────
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Email addresses
    (re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I), "[EMAIL]"),
    # Credit card numbers (basic Luhn-format, 13–19 digits with optional separators)
    (re.compile(r"\b(?:\d[ \-]?){13,19}\b"), "[CARD]"),
    # SSN — US format
    (re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b"), "[SSN]"),
    # Phone numbers — common formats
    (re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"), "[PHONE]"),
    # API keys / secrets — long hex or base64 strings after common prefixes
    (re.compile(r"(sk-|cxo-|whsec_|pk_live_|sk_live_|sk_test_)[A-Za-z0-9_\-]{8,}", re.I), r"\1[REDACTED]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I), "Bearer [REDACTED]"),
]


def redact_pii(value: Any, depth: int = 0) -> Any:
    """Recursively redact PII from any JSON-compatible value."""
    if depth > 10:
        return value  # prevent infinite recursion on deeply nested structures
    if isinstance(value, str):
        for pattern, replacement in _PII_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {k: redact_pii(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_pii(item, depth + 1) for item in value]
    return value


# ── Request ID middleware (checklist item 13 — traceability) ──────────────
class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique X-Request-ID to every request and response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ── Rate limiting — token bucket (checklist item 6 — fault tolerance) ─────
class RateLimiter:
    """
    Simple in-process token bucket rate limiter.
    For multi-replica deployments, replace with Redis-backed implementation.
    """

    def __init__(self, rate: int = 100, per_seconds: int = 60) -> None:
        self.rate = rate          # max requests
        self.per = per_seconds    # per window (seconds)
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.per
        bucket = self._buckets[key]
        # Remove old entries outside the window
        self._buckets[key] = [t for t in bucket if t > window_start]
        if len(self._buckets[key]) >= self.rate:
            return False
        self._buckets[key].append(now)
        return True

    def cleanup(self) -> None:
        """Remove empty buckets — call periodically to prevent memory growth."""
        now = time.monotonic()
        window_start = now - self.per
        self._buckets = defaultdict(
            list,
            {k: [t for t in v if t > window_start] for k, v in self._buckets.items() if v}
        )


# Global limiter — 200 requests / 60 seconds per IP
_rate_limiter = RateLimiter(rate=200, per_seconds=60)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting per client IP. Health check is exempt."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.is_allowed(client_ip):
            return Response(
                content='{"detail":"Rate limit exceeded. Max 200 requests/minute."}',
                status_code=429,
                media_type="application/json",
            )
        return await call_next(request)


# ── Idempotency key store (checklist item 6) ──────────────────────────────
class IdempotencyStore:
    """
    In-process idempotency store with TTL.
    For production multi-replica, replace with Redis.
    TTL: 24 hours.
    """

    TTL = 86_400  # seconds

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def _key(self, idempotency_key: str, endpoint: str) -> str:
        return hashlib.sha256(f"{endpoint}:{idempotency_key}".encode()).hexdigest()

    def get(self, idempotency_key: str, endpoint: str) -> Any | None:
        k = self._key(idempotency_key, endpoint)
        if k in self._store:
            timestamp, result = self._store[k]
            if time.time() - timestamp < self.TTL:
                return result
            del self._store[k]
        return None

    def set(self, idempotency_key: str, endpoint: str, result: Any) -> None:
        k = self._key(idempotency_key, endpoint)
        self._store[k] = (time.time(), result)

    def cleanup(self) -> None:
        now = time.time()
        self._store = {k: v for k, v in self._store.items() if now - v[0] < self.TTL}


idempotency_store = IdempotencyStore()
