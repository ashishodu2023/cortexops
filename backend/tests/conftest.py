"""Backend test fixtures — isolated SQLite DB, stubbed API-key auth, no outbound email."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_DB_DIR = tempfile.mkdtemp(prefix="cortexops-test-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_DIR}/test.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["INTERNAL_API_KEY"] = "test-internal-key"
os.environ["JWT_SECRET"] = "test-jwt-secret-for-pytest-only"
for _var in ("RESEND_API_KEY", "SENDGRID_API_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_WEBHOOK_ID"):
    os.environ.pop(_var, None)
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import get_current_key_info  # noqa: E402
from app.main import app  # noqa: E402
from app.security import _rate_limiter  # noqa: E402
from app.tiers import TierInfo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PROJECT = "payments-agent"
INTERNAL_KEY = "test-internal-key"


@pytest.fixture
def tier_info() -> TierInfo:
    return TierInfo(project=PROJECT, tier="pro", key_id="test-key")


@pytest.fixture
def client(tier_info):
    app.dependency_overrides[get_current_key_info] = lambda: tier_info
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # The per-IP limiter is process-global and every TestClient request comes from the same
    # address, so without a reset the suite starts getting 429s once it passes 200 requests.
    _rate_limiter._buckets.clear()
    yield
    _rate_limiter._buckets.clear()


@pytest.fixture(autouse=True)
def _no_email_providers(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
