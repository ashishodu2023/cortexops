"""Startup secret checks: billing secrets are required unless BILLING_ENABLED is false."""
from __future__ import annotations

import asyncio

import pytest
from app import main
from app.config import Settings
from fastapi.testclient import TestClient

STRONG = {"JWT_SECRET": "a" * 64, "INTERNAL_API_KEY": "b" * 64}
POSTGRES_URL = "postgresql+asyncpg://u:p@db:5432/cortexops"


def _paypal_issue(issues: list[str]) -> bool:
    return any("PAYPAL_WEBHOOK_ID" in i for i in issues)


def test_paypal_webhook_id_required_by_default():
    assert _paypal_issue(main._collect_secret_issues(STRONG))


@pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", ""])
def test_paypal_webhook_id_required_when_billing_enabled(value):
    assert _paypal_issue(main._collect_secret_issues({**STRONG, "BILLING_ENABLED": value}))


@pytest.mark.parametrize("value", ["false", "0", "no", "off", " False "])
def test_billing_disabled_skips_paypal_requirement(value):
    assert main._collect_secret_issues({**STRONG, "BILLING_ENABLED": value}) == []


def test_billing_disabled_still_requires_core_secrets():
    issues = main._collect_secret_issues({"BILLING_ENABLED": "false", "JWT_SECRET": "dev-secret"})
    assert any("JWT_SECRET" in i for i in issues)
    assert any("INTERNAL_API_KEY" in i for i in issues)
    assert not _paypal_issue(issues)


def _start_in_production(monkeypatch, env: dict) -> None:
    for key in ("JWT_SECRET", "INTERNAL_API_KEY", "PAYPAL_WEBHOOK_ID", "BILLING_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    prod = Settings(environment="production", database_url="postgresql+asyncpg://u:p@db:5432/cortexops")
    monkeypatch.setattr(main, "settings", prod)
    asyncio.run(main.validate_secrets())


def test_production_startup_without_billing(monkeypatch):
    _start_in_production(monkeypatch, {**STRONG, "BILLING_ENABLED": "false"})


def test_production_startup_with_billing_still_fails_closed(monkeypatch):
    with pytest.raises(RuntimeError, match="PAYPAL_WEBHOOK_ID"):
        _start_in_production(monkeypatch, STRONG)


# The tests below boot the real app, so they fail if the check is not wired into the lifespan.

def _boot(monkeypatch, env: dict, calls: list[str], environment: str = "production",
          database_url: str = POSTGRES_URL) -> None:
    for key in ("JWT_SECRET", "INTERNAL_API_KEY", "PAYPAL_WEBHOOK_ID", "BILLING_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(main, "settings", Settings(environment=environment, database_url=database_url))

    async def fake_init_db():
        calls.append("init_db")

    # No real PostgreSQL in tests: skip schema creation, and record whether startup got past the checks.
    monkeypatch.setattr(main, "init_db", fake_init_db)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        calls.append("served")


@pytest.mark.parametrize("env,reason", [
    ({}, "JWT_SECRET not set"),
    ({**STRONG, "JWT_SECRET": "dev-secret"}, "JWT_SECRET not set or uses default"),
    ({**STRONG, "INTERNAL_API_KEY": "dev_internal_key"}, "INTERNAL_API_KEY not set or uses default"),
    (STRONG, "PAYPAL_WEBHOOK_ID"),
])
def test_production_app_refuses_to_start_with_bad_secrets(monkeypatch, env, reason):
    calls: list[str] = []
    with pytest.raises(RuntimeError, match=reason):
        _boot(monkeypatch, env, calls)
    assert calls == []  # failed before touching the database


def test_production_app_refuses_to_start_on_sqlite(monkeypatch):
    calls: list[str] = []
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        _boot(monkeypatch, {**STRONG, "BILLING_ENABLED": "false"}, calls, database_url="sqlite+aiosqlite:///./x.db")
    assert calls == []


@pytest.mark.parametrize("env", [
    {**STRONG, "BILLING_ENABLED": "false"},
    {**STRONG, "PAYPAL_WEBHOOK_ID": "WH-123"},
])
def test_production_app_starts_with_good_config(monkeypatch, env):
    calls: list[str] = []
    _boot(monkeypatch, env, calls)
    assert calls == ["init_db", "served"]


def test_dev_app_starts_with_weak_secrets_and_only_warns(monkeypatch, caplog):
    calls: list[str] = []
    with caplog.at_level("WARNING", logger="app.main"):
        _boot(monkeypatch, {"JWT_SECRET": "dev-secret"}, calls, environment="development",
              database_url="sqlite+aiosqlite:///./x.db")
    assert calls == ["init_db", "served"]
    assert "DEV SECURITY WARNING: JWT_SECRET not set or uses default" in caplog.text
