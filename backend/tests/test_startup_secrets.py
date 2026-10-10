"""Startup secret checks: billing secrets are required unless BILLING_ENABLED is false."""
from __future__ import annotations

import asyncio

import pytest
from app import main
from app.config import Settings

STRONG = {"JWT_SECRET": "a" * 64, "INTERNAL_API_KEY": "b" * 64}


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
