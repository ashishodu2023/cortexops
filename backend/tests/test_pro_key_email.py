"""Pro key provisioning sends the key by email automatically (Stripe + PayPal) and can be re-sent by admins."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import uuid

import pytest
from app.main import app
from app.routers.admin import ResendKeyEmailRequest, admin_resend_key_email
from app.services import email as email_service
from app.services import provisioning
from conftest import INTERNAL_KEY
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ADMIN = {"X-Internal-Key": INTERNAL_KEY}


def _expire_key(key_id: str) -> None:
    db_path = os.environ["DATABASE_URL"].split("///", 1)[1]
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE api_keys SET expires_at = '2000-01-01 00:00:00.000000' WHERE id = ?", (key_id,))


def _run_with_sessions(make_coro):
    """Run coroutines that need independent DB sessions on a fresh loop and engine."""
    async def _main():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        try:
            return await make_coro(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()
    return asyncio.run(_main())


class Outbox:
    def __init__(self):
        self.sent: list[dict] = []
        self.fail: set[str] = set()

    def provider(self, name):
        async def _send(api_key, to, subject, text):
            if name in self.fail:
                return False
            self.sent.append({"provider": name, "to": to, "subject": subject, "text": text})
            return True
        return _send

    def raw_key(self, i: int = -1) -> str:
        return re.search(r"export CORTEXOPS_API_KEY=(\S+)", self.sent[i]["text"]).group(1)


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(email_service, "_send_resend", box.provider("resend"))
    monkeypatch.setattr(email_service, "_send_sendgrid", box.provider("sendgrid"))
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.test")
    return box


def _project() -> str:
    return f"proj-{uuid.uuid4().hex[:8]}"


def _stripe_checkout(client, project: str, *, metadata_email: str | None, customer_email: str | None = None):
    sess = {"id": f"cs_test_{uuid.uuid4().hex}", "metadata": {"project": project}}
    if metadata_email:
        sess["metadata"]["email"] = metadata_email
    if customer_email:
        sess["customer_details"] = {"email": customer_email}
    event = {"type": "checkout.session.completed", "data": {"object": sess}}
    r = client.post("/v1/billing/webhook/stripe", content=json.dumps(event))
    assert r.status_code == 200, r.text
    return r.json()


def _keys(client, project: str) -> list[dict]:
    return client.get("/v1/admin/keys", params={"project": project}, headers=ADMIN).json()


def _audit(client, project: str) -> list[dict]:
    return client.get("/v1/admin/auth-audit", params={"project": project}, headers=ADMIN).json()


def test_stripe_checkout_provisions_and_emails_key(client, outbox):
    project = _project()
    body = _stripe_checkout(client, project, metadata_email="dev@acme.io")
    assert body["provision"] == "provisioned"
    assert body["email"] == "sent"

    assert len(outbox.sent) == 1
    mail = outbox.sent[0]
    assert mail["provider"] == "resend"
    assert mail["to"] == "dev@acme.io"
    assert project in mail["text"]
    assert outbox.raw_key().startswith("cxo-")

    keys = _keys(client, project)
    assert [(k["tier"], k["is_active"]) for k in keys] == [("pro", True)]
    events = {(a["event"], a["outcome"]) for a in _audit(client, project)}
    assert ("pro_key_provisioned", "success") in events
    assert ("pro_key_email", "success") in events


def test_stripe_webhook_retry_is_idempotent(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    retry = _stripe_checkout(client, project, metadata_email="dev@acme.io")
    assert retry["provision"] == "already_provisioned"
    assert len(_keys(client, project)) == 1
    assert len(outbox.sent) == 1


def test_stripe_falls_back_to_customer_details_email(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email=None, customer_email="billing@acme.io")
    assert outbox.sent[0]["to"] == "billing@acme.io"


def test_resend_failure_falls_back_to_sendgrid(client, outbox):
    outbox.fail.add("resend")
    project = _project()
    body = _stripe_checkout(client, project, metadata_email="dev@acme.io")
    assert body["email"] == "sent"
    assert outbox.sent[0]["provider"] == "sendgrid"


def test_undelivered_email_is_audited(client, monkeypatch):
    project = _project()
    body = _stripe_checkout(client, project, metadata_email="dev@acme.io")
    assert body["email"] == "not_configured"
    events = {(a["event"], a["outcome"], a["detail"]) for a in _audit(client, project)}
    assert ("pro_key_email", "failure", "status=not_configured") in events


def test_paypal_activation_provisions_and_emails_key(client, outbox):
    project = _project()
    event = {
        "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
        "resource": {
            "id": f"I-{uuid.uuid4().hex[:12].upper()}",
            "custom_id": project,
            "subscriber": {"email_address": "owner@acme.io"},
        },
    }
    r = client.post("/v1/billing/paypal/webhook", content=json.dumps(event))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "sent"
    assert outbox.sent[0]["to"] == "owner@acme.io"

    again = client.post("/v1/billing/paypal/webhook", content=json.dumps(event))
    assert again.json() == {"status": "already_provisioned"}
    assert len(outbox.sent) == 1


def test_admin_resend_rotates_and_emails_new_key(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    old = _keys(client, project)[0]
    first_raw = outbox.raw_key()

    r = client.post(f"/v1/admin/keys/{old['id']}/resend-email", json={"email": "dev@acme.io"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["old_key_id"] == old["id"]
    assert "cxo-" not in json.dumps(body)

    second_raw = outbox.raw_key()
    assert second_raw != first_raw
    keys = {k["id"]: k for k in _keys(client, project)}
    assert keys[old["id"]]["is_active"] is False
    assert keys[body["new_key_id"]]["is_active"] is True
    assert keys[body["new_key_id"]]["tier"] == "pro"


def test_admin_resend_failure_leaves_key_unchanged(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    old = _keys(client, project)[0]
    outbox.fail.update({"resend", "sendgrid"})

    r = client.post(f"/v1/admin/keys/{old['id']}/resend-email", json={"email": "dev@acme.io"}, headers=ADMIN)
    assert r.status_code == 502
    keys = _keys(client, project)
    assert [k["id"] for k in keys if k["is_active"]] == [old["id"]]
    assert len(outbox.sent) == 1  # only the original provisioning email

    outbox.fail.clear()
    retry = client.post(f"/v1/admin/keys/{old['id']}/resend-email", json={"email": "dev@acme.io"}, headers=ADMIN)
    assert retry.status_code == 200, retry.text
    assert [k["id"] for k in _keys(client, project) if k["is_active"]] == [retry.json()["new_key_id"]]


def test_admin_resend_commit_failure_sends_nothing(client, outbox, monkeypatch):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    old = _keys(client, project)[0]
    sent_before = len(outbox.sent)

    real_commit = AsyncSession.commit
    armed = {"on": True}

    async def failing_commit(self):
        if armed["on"]:
            armed["on"] = False
            raise OperationalError("COMMIT", {}, Exception("database is down"))
        return await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post(f"/v1/admin/keys/{old['id']}/resend-email", json={"email": "dev@acme.io"}, headers=ADMIN)
    assert r.status_code == 500
    assert len(outbox.sent) == sent_before
    assert [(k["id"], k["is_active"]) for k in _keys(client, project)] == [(old["id"], True)]


def test_admin_resend_rejects_free_tier_key(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    old = _keys(client, project)[0]
    r = client.post(f"/v1/admin/keys/{old['id']}/upgrade", json={"tier": "free"}, headers=ADMIN)
    assert r.status_code == 200, r.text

    r = client.post(f"/v1/admin/keys/{old['id']}/resend-email", json={"email": "dev@acme.io"}, headers=ADMIN)
    assert r.status_code == 400
    assert "Pro" in r.json()["detail"]
    assert len(outbox.sent) == 1
    assert [(k["id"], k["is_active"]) for k in _keys(client, project)] == [(old["id"], True)]


def test_admin_resend_rejects_expired_key(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    old = _keys(client, project)[0]
    _expire_key(old["id"])

    r = client.post(f"/v1/admin/keys/{old['id']}/resend-email", json={"email": "dev@acme.io"}, headers=ADMIN)
    assert r.status_code == 400
    assert "expired" in r.json()["detail"]
    assert len(outbox.sent) == 1


def test_expired_pro_key_does_not_block_reprovisioning(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    _expire_key(_keys(client, project)[0]["id"])

    again = _stripe_checkout(client, project, metadata_email="dev@acme.io")
    assert again["provision"] == "provisioned"
    assert len(outbox.sent) == 2


def test_concurrent_resends_issue_one_key(client, outbox):
    project = _project()
    _stripe_checkout(client, project, metadata_email="dev@acme.io")
    old = _keys(client, project)[0]

    async def _resend(sessions):
        async with sessions() as db:
            try:
                await admin_resend_key_email(old["id"], ResendKeyEmailRequest(email="dev@acme.io"), db, None)
                return 200
            except HTTPException as exc:
                return exc.status_code

    statuses = _run_with_sessions(lambda sessions: asyncio.gather(_resend(sessions), _resend(sessions)))
    assert sorted(statuses) == [200, 409]
    assert len(outbox.sent) == 2  # provisioning + exactly one resend
    assert len([k for k in _keys(client, project) if k["is_active"]]) == 1


def test_concurrent_webhooks_provision_one_key(client, outbox, monkeypatch):
    project = _project()
    real_audit = provisioning.record_auth_event

    async def slow_audit(*args, **kwargs):
        await asyncio.sleep(0.05)  # widen the gap between the active-key lookup and the commit
        await real_audit(*args, **kwargs)

    monkeypatch.setattr(provisioning, "record_auth_event", slow_audit)

    async def _provision(sessions, ref):
        async with sessions() as db:
            result = await provisioning.provision_pro_key(
                db, project=project, email="dev@acme.io", source="stripe", ref=ref,
            )
            return result.status

    statuses = _run_with_sessions(
        lambda sessions: asyncio.gather(_provision(sessions, "cs_a"), _provision(sessions, "cs_b")),
    )
    assert sorted(statuses) == ["already_provisioned", "provisioned"]
    assert len(_keys(client, project)) == 1
    assert len(outbox.sent) == 1


def test_admin_resend_requires_internal_key(client):
    r = client.post("/v1/admin/keys/whatever/resend-email", json={"email": "dev@acme.io"})
    assert r.status_code == 401
