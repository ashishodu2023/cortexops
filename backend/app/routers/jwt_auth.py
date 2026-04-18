"""
JWT support for CortexOps.

Flow:
    1. User has a cxo- API key (long-lived, stored hashed in DB)
    2. POST /v1/auth/token  with X-API-Key → returns short-lived JWT (1 hour)
    3. Use JWT in Authorization: Bearer <token> for subsequent requests
    4. JWT carries project, tier, scope — no DB lookup on every request

Why JWT alongside API keys:
    - API keys: long-lived, for SDK/CLI/CI — hits DB on every request
    - JWT tokens: short-lived, for dashboard/browser — stateless, no DB hit
    - Rotating a JWT: just let it expire (max 1 hour exposure window)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import hash_key
from ..db import get_db
from ..models.records import ApiKey

router = APIRouter(prefix="/v1/auth", tags=["auth"])

# ── JWT secret ────────────────────────────────────────────────────────────
_JWT_SECRET = os.getenv("JWT_SECRET", "cortexops-dev-jwt-secret-change-in-production")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_SECONDS = 3600  # 1 hour

_bearer = HTTPBearer(auto_error=False)


# ── Minimal JWT implementation (no external dependency) ───────────────────
def _b64_encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    return urlsafe_b64decode(data + "=" * padding)


def _sign(payload: dict, secret: str) -> str:
    """Issue a HS256 JWT."""
    header = _b64_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body   = _b64_encode(json.dumps(payload).encode())
    sig    = _b64_encode(
        hmac.HMAC(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{body}.{sig}"


def _verify(token: str, secret: str) -> dict:
    """Verify a HS256 JWT. Raises ValueError on failure."""
    try:
        header, body, sig = token.split(".")
    except ValueError:
        raise ValueError("Malformed JWT")

    expected_sig = _b64_encode(
        hmac.HMAC(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Invalid JWT signature")

    payload = json.loads(_b64_decode(body))
    if payload.get("exp", 0) < time.time():
        raise ValueError("JWT expired")

    return payload


# ── Schemas ───────────────────────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = _JWT_EXPIRY_SECONDS
    project: str
    tier: str
    scope: str


class TokenPayload(BaseModel):
    project: str
    tier: str
    scope: str
    key_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenResponse)
async def issue_token(
    db: AsyncSession = Depends(get_db),
    raw_key: str | None = None,  # from X-API-Key header via dependency
):
    """
    Exchange a long-lived cxo- API key for a short-lived JWT (1 hour).

    Use JWTs for:
    - Dashboard authentication (browser-safe, short expiry)
    - Reducing DB load (JWT is stateless — no DB lookup per request)

    The JWT carries: project, tier, scope, key_id, iat, exp
    """
    raise HTTPException(
        status_code=501,
        detail="Use POST /v1/auth/token with X-API-Key header via the dedicated auth dependency."
    )


@router.post("/token/issue", response_model=TokenResponse)
async def issue_jwt(
    db: AsyncSession = Depends(get_db),
    api_key_header: str | None = Security(
        __import__('fastapi.security', fromlist=['APIKeyHeader']).APIKeyHeader(
            name="X-API-Key", auto_error=False
        )
    ),
):
    """
    Exchange a cxo- API key for a short-lived JWT.

    Request:
        POST /v1/auth/token/issue
        X-API-Key: cxo-...

    Response:
        {
          "access_token": "eyJ...",
          "token_type": "bearer",
          "expires_in": 3600,
          "project": "payments-agent",
          "tier": "pro",
          "scope": "read_write"
        }

    Then use the JWT:
        Authorization: Bearer eyJ...
    """
    if not api_key_header:
        raise HTTPException(status_code=401, detail="X-API-Key header required")

    hashed = hash_key(api_key_header)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.is_active)
    )
    key_record = result.scalar_one_or_none()

    if not key_record:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    # Check expiry
    from datetime import datetime
    if key_record.expires_at and datetime.utcnow() > key_record.expires_at:
        raise HTTPException(
            status_code=401,
            detail={"error": "key_expired", "expired_at": key_record.expires_at.isoformat()}
        )

    scope = getattr(key_record, "scope", "read_write") or "read_write"
    now   = int(time.time())

    payload = {
        "sub":     key_record.project,
        "project": key_record.project,
        "tier":    key_record.tier,
        "scope":   scope,
        "key_id":  key_record.id,
        "iat":     now,
        "exp":     now + _JWT_EXPIRY_SECONDS,
    }

    token = _sign(payload, _JWT_SECRET)

    return TokenResponse(
        access_token=token,
        project=key_record.project,
        tier=key_record.tier,
        scope=scope,
    )


@router.get("/token/verify")
async def verify_jwt(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
):
    """
    Verify a JWT and return its decoded payload.
    Use this from the dashboard to validate a session token.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")

    try:
        payload = _verify(credentials.credentials, _JWT_SECRET)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    ttl = int(payload["exp"] - time.time())
    return {
        "valid":   True,
        "project": payload.get("project"),
        "tier":    payload.get("tier"),
        "scope":   payload.get("scope"),
        "key_id":  payload.get("key_id"),
        "expires_in_seconds": ttl,
    }


# ── JWT dependency for routes that accept both API key and JWT ─────────────
async def get_jwt_payload(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> dict:
    """
    FastAPI dependency — validates Bearer JWT and returns payload.
    Use in routes that the dashboard calls directly (avoids DB lookup).
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization: Bearer <jwt> required. Get a token from POST /v1/auth/token/issue"
        )
    try:
        return _verify(credentials.credentials, _JWT_SECRET)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))