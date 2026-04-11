"""
Tier enforcement — free vs pro limits.

Free tier limits (enforced server-side):
  - 5,000 hosted traces per calendar month
  - 7-day trace retention
  - No Slack alerts, LLM judge, or prompt versioning

Pro tier:
  - Unlimited hosted traces
  - 90-day trace retention
  - All features unlocked

Usage in route handlers:
    from .tiers import require_pro, check_trace_quota, TierInfo
    key_info = await get_current_key_info(raw_key, db)
    check_trace_quota(key_info)          # raises 429 if free and over limit
    require_pro(key_info, "Slack alerts") # raises 402 if free
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException


# ── Tier constants ─────────────────────────────────────────────────────────
FREE_MONTHLY_TRACE_LIMIT = 5_000
FREE_RETENTION_DAYS      = 7
PRO_RETENTION_DAYS       = 90

PRO_ONLY_FEATURES = [
    "Slack alerts",
    "LLM judge scoring",
    "Prompt versioning",
    "Extended trace retention (90 days)",
]


@dataclass
class TierInfo:
    """Resolved tier information for the current authenticated request."""
    project: str
    tier: str           # "free" | "pro"
    key_id: str
    monthly_traces: int = 0  # current month usage — populated by check_trace_quota
    scope: str = "read_write"   # "read_write" | "read_only"

    @property
    def is_pro(self) -> bool:
        return self.tier == "pro"

    @property
    def is_free(self) -> bool:
        return self.tier == "free"

    @property
    def trace_limit(self) -> int | None:
        """None = unlimited (Pro). Integer = monthly cap (Free)."""
        return None if self.is_pro else FREE_MONTHLY_TRACE_LIMIT

    @property
    def retention_days(self) -> int:
        return PRO_RETENTION_DAYS if self.is_pro else FREE_RETENTION_DAYS


def require_pro(tier_info: TierInfo, feature: str = "This feature") -> None:
    """
    Raise HTTP 402 Payment Required if the key is on the free tier.
    Call this at the top of any Pro-only route handler.
    """
    if tier_info.is_free:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "pro_required",
                "message": f"{feature} requires a CortexOps Pro subscription.",
                "upgrade_url": "https://getcortexops.com/#pricing",
                "current_tier": "free",
            },
        )


def check_trace_quota(tier_info: TierInfo) -> None:
    """
    Raise HTTP 429 Too Many Requests if a free-tier project has
    exceeded 5,000 traces this calendar month.
    """
    if tier_info.is_pro:
        return  # unlimited — no check needed

    if tier_info.monthly_traces >= FREE_MONTHLY_TRACE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "trace_quota_exceeded",
                "message": (
                    f"Free tier limit: {FREE_MONTHLY_TRACE_LIMIT:,} traces/month. "
                    f"You have used {tier_info.monthly_traces:,} this month."
                ),
                "limit": FREE_MONTHLY_TRACE_LIMIT,
                "used": tier_info.monthly_traces,
                "upgrade_url": "https://getcortexops.com/#pricing",
                "resets_at": _month_reset_iso(),
            },
        )


def _month_reset_iso() -> str:
    """ISO timestamp for the start of next calendar month (UTC)."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        nxt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        nxt = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return nxt.isoformat()

def require_scope(tier_info: "TierInfo", required: str = "read_write") -> None:
    """
    Raise HTTP 403 if the key is read_only and a write operation is attempted.
    Call at the top of any write endpoint (POST, PUT, DELETE).
    """
    if required == "read_write" and getattr(tier_info, "scope", "read_write") == "read_only":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "insufficient_scope",
                "message": "This endpoint requires a read_write key. Your key has read_only scope.",
                "required_scope": "read_write",
                "current_scope": "read_only",
            },
        )