"""Writers that race on the 0002_uniqueness constraints end with exactly one row, never a 500.

Races are forced either with two real sessions on separate connections, or by making a writer
read stale state so that its insert collides with a row committed in the meantime.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import uuid

import pytest
from app.models.schemas import EvalSummaryIngest
from app.routers import evals, prompts
from app.services import provisioning
from app.tiers import TierInfo
from conftest import INTERNAL_KEY, PROJECT
from fastapi import Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ADMIN = {"X-Internal-Key": INTERNAL_KEY}
DB_PATH = os.environ["DATABASE_URL"].split("///", 1)[1]


def _sql(statement: str, params: tuple = ()) -> list:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(statement, params).fetchall()


def _run_with_sessions(make_coro):
    async def _main():
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        try:
            return await make_coro(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()
    return asyncio.run(_main())


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ── Prompt versions ─────────────────────────────────────────────────────────

def _commit_prompt(client, name, content):
    return client.post("/v1/prompts", json={"project": PROJECT, "prompt_name": name, "content": content})


def _versions(client, name):
    r = client.get("/v1/prompts", params={"project": PROJECT, "prompt_name": name})
    return [(v["version"], v["content"]) for v in r.json()]


def test_prompt_commit_retries_next_version_after_conflict(client, monkeypatch):
    name = _unique("race")
    assert _commit_prompt(client, name, "v1").status_code == 201
    real_latest = prompts.latest_prompt_version
    calls = {"n": 0}

    async def stale_latest(db, project, prompt_name):
        latest = await real_latest(db, project, prompt_name)
        calls["n"] += 1
        if calls["n"] == 1:  # a concurrent commit takes v2 between our read and our insert
            _sql(
                "INSERT INTO prompt_versions (id, project, prompt_name, version, content, model, temperature, "
                "commit_message, author, created_at) VALUES (?, ?, ?, 2, 'racer', '', 0.7, '', '', CURRENT_TIMESTAMP)",
                (str(uuid.uuid4()), PROJECT, name),
            )
        return latest

    monkeypatch.setattr(prompts, "latest_prompt_version", stale_latest)
    r = _commit_prompt(client, name, "mine")
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 3
    assert calls["n"] == 2
    assert _versions(client, name) == [(3, "mine"), (2, "racer"), (1, "v1")]


def test_prompt_commit_gives_up_with_409_after_bounded_retries(client, monkeypatch):
    name = _unique("stuck")
    assert _commit_prompt(client, name, "v1").status_code == 201
    calls = {"n": 0}

    async def always_stale(db, project, prompt_name):
        calls["n"] += 1
        return None  # always allocates v1, which exists

    monkeypatch.setattr(prompts, "latest_prompt_version", always_stale)
    r = _commit_prompt(client, name, "never")
    assert r.status_code == 409
    assert calls["n"] == prompts.PROMPT_VERSION_ATTEMPTS
    assert _versions(client, name) == [(1, "v1")]


@pytest.mark.parametrize("project_exists", [True, False])
def test_concurrent_prompt_commits_get_distinct_versions(client, project_exists):
    name = _unique("parallel")
    project = _unique("proj")
    if project_exists:  # otherwise the writers also race on creating the project row
        _sql("INSERT INTO projects (id, name, description, created_at) VALUES (?, ?, '', CURRENT_TIMESTAMP)",
             (str(uuid.uuid4()), project))
    tier_info = TierInfo(project=project, tier="pro", key_id="k")

    async def _commit(sessions, content):
        async with sessions() as db:
            body = prompts.PromptCreate(project=project, prompt_name=name, content=content)
            pv = await prompts.create_prompt_version(body, db, tier_info)
            version = pv.version
            await db.commit()
            return version

    versions = _run_with_sessions(lambda s: asyncio.gather(_commit(s, "a"), _commit(s, "b"), _commit(s, "c")))
    assert sorted(versions) == [1, 2, 3]
    assert _sql("SELECT COUNT(*) FROM projects WHERE name = ?", (project,)) == [(1,)]


# ── Eval ingest ─────────────────────────────────────────────────────────────

def _ingest_body(run_id: str, **extra) -> dict:
    return {
        "run_id": run_id,
        "project": PROJECT,
        "total_cases": 1,
        "passed": 1,
        "failed": 0,
        "task_completion_rate": 1.0,
        "tool_accuracy": 100.0,
        "latency_p50_ms": 10.0,
        "latency_p95_ms": 20.0,
        "case_results": [{
            "case_id": "c1", "passed": True, "score": 100.0,
            "task_completion": True, "tool_accuracy": 100.0, "latency_ms": 10.0,
        }],
        **extra,
    }


def _run_rows(run_id: str) -> tuple[int, int]:
    runs = _sql("SELECT COUNT(*) FROM eval_runs WHERE id = ?", (run_id,))[0][0]
    cases = _sql("SELECT COUNT(*) FROM case_results WHERE run_id = ?", (run_id,))[0][0]
    return runs, cases


def test_ingest_replay_returns_stored_run(client):
    run_id = str(uuid.uuid4())
    first = client.post("/v1/evals/ingest", json=_ingest_body(run_id))
    assert first.status_code == 201, first.text

    replay = client.post("/v1/evals/ingest", json=_ingest_body(run_id, passed=0, failed=1))
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()  # first write wins
    assert _run_rows(run_id) == (1, 1)


def test_ingest_run_id_from_other_project_conflicts(client):
    run_id = str(uuid.uuid4())
    other = _unique("other")
    _sql("INSERT INTO projects (id, name, description, created_at) VALUES (?, ?, '', CURRENT_TIMESTAMP)",
         (str(uuid.uuid4()), other))
    _sql(
        "INSERT INTO eval_runs (id, project, dataset_version, status, total_cases, passed, failed, warnings, "
        "task_completion_rate, tool_accuracy, latency_p50_ms, latency_p95_ms, regressions, created_at) "
        "VALUES (?, ?, 1, 'completed', 9, 9, 0, 0, 1.0, 100.0, 1.0, 1.0, 0, CURRENT_TIMESTAMP)",
        (run_id, other),
    )
    r = client.post("/v1/evals/ingest", json=_ingest_body(run_id))
    assert r.status_code == 409
    assert "another project" in r.json()["detail"]
    assert _sql("SELECT project, total_cases FROM eval_runs WHERE id = ?", (run_id,)) == [(other, 9)]


def test_ingest_insert_conflict_returns_existing_run(client, monkeypatch):
    run_id = str(uuid.uuid4())
    assert client.post("/v1/evals/ingest", json=_ingest_body(run_id)).status_code == 201
    real_load = evals._load_run
    calls = {"n": 0}

    async def stale_load(db, rid):
        calls["n"] += 1
        return None if calls["n"] == 1 else await real_load(db, rid)  # missed the concurrent insert

    monkeypatch.setattr(evals, "_load_run", stale_load)
    r = client.post("/v1/evals/ingest", json=_ingest_body(run_id))
    assert r.status_code == 200, r.text
    assert _run_rows(run_id) == (1, 1)


def test_concurrent_ingests_of_same_run_store_one_run(client):
    run_id = str(uuid.uuid4())
    tier_info = TierInfo(project=PROJECT, tier="pro", key_id="k")
    body = EvalSummaryIngest(**_ingest_body(run_id))

    async def _ingest(sessions):
        async with sessions() as db:
            response = Response(status_code=201)
            await evals.ingest_eval_summary(body, response, db, tier_info)
            await db.commit()
            return response.status_code

    statuses = _run_with_sessions(lambda s: asyncio.gather(_ingest(s), _ingest(s)))
    assert sorted(statuses) == [200, 201]
    assert _run_rows(run_id) == (1, 1)


# ── Pro key provisioning ────────────────────────────────────────────────────

def _keys(client, project: str) -> list[dict]:
    return client.get("/v1/admin/keys", params={"project": project}, headers=ADMIN).json()


def _provision_concurrently(project: str, refs: list[str]) -> list[str]:
    async def _provision(sessions, ref):
        async with sessions() as db:
            result = await provisioning.provision_pro_key(db, project=project, email=None, source="stripe", ref=ref)
            return result.status

    return _run_with_sessions(lambda s: asyncio.gather(*(_provision(s, ref) for ref in refs)))


def test_concurrent_duplicate_webhook_deliveries_provision_one_key(client):
    project = _unique("proj")
    statuses = _provision_concurrently(project, ["cs_same", "cs_same", "cs_same"])
    assert sorted(statuses) == ["already_provisioned", "already_provisioned", "provisioned"]
    assert [(k["tier"], k["is_active"]) for k in _keys(client, project)] == [("pro", True)]


def test_provision_conflict_returns_winner_key(client, monkeypatch):
    project = _unique("proj")
    winner = _provision_concurrently(project, ["cs_first"])
    assert winner == ["provisioned"]
    winner_id = _keys(client, project)[0]["id"]

    # A replica that read "no key yet" just before the winner committed, then inserts.
    real_scalar = provisioning.AsyncSession.scalar
    blind = {"left": 2}

    async def stale_scalar(self, statement, *args, **kwargs):
        if blind["left"] > 0 and "api_keys" in str(statement):
            blind["left"] -= 1
            return None
        return await real_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(provisioning.AsyncSession, "scalar", stale_scalar)
    statuses = _provision_concurrently(project, ["cs_first"])
    assert statuses == ["already_provisioned"]
    assert [k["id"] for k in _keys(client, project)] == [winner_id]


def test_rotated_provisioned_key_is_not_constrained(client, monkeypatch):
    project = _unique("proj")
    _provision_concurrently(project, ["cs_one"])
    key = _keys(client, project)[0]
    monkeypatch.setattr(
        "app.routers.admin.deliver_pro_key", lambda *a, **k: asyncio.sleep(0, result=("sent", "test")),
    )
    r = client.post(f"/v1/admin/keys/{key['id']}/resend-email", json={"email": "dev@acme.io"}, headers=ADMIN)
    assert r.status_code == 200, r.text

    # A later payment event for the same project is satisfied by the rotated key.
    assert _provision_concurrently(project, ["cs_two"]) == ["already_provisioned"]
    assert sum(k["is_active"] for k in _keys(client, project)) == 1


def test_paypal_resubscribe_after_cancel_provisions_again(client):
    project = _unique("proj")

    def _paypal(event_type, event_id, sub_id):
        payload = {"id": event_id, "event_type": event_type, "resource": {"id": sub_id, "custom_id": project}}
        r = client.post("/v1/billing/paypal/webhook", content=json.dumps(payload))
        assert r.status_code == 200, r.text
        return r.json()

    assert _paypal("BILLING.SUBSCRIPTION.ACTIVATED", "WH-1", "I-A")["status"] == "processed"
    assert _paypal("BILLING.SUBSCRIPTION.ACTIVATED", "WH-1", "I-A") == {"status": "already_provisioned"}
    _paypal("BILLING.SUBSCRIPTION.CANCELLED", "WH-2", "I-A")
    assert _paypal("BILLING.SUBSCRIPTION.ACTIVATED", "WH-3", "I-B")["status"] == "processed"

    keys = {k["id"]: k for k in _keys(client, project)}
    assert sorted(k["tier"] for k in keys.values()) == ["free", "pro"]
    old = next(k for k in keys.values() if k["tier"] == "free")

    # Re-upgrading the cancelled key would give the project two active provisioned Pro keys.
    r = client.post(f"/v1/admin/keys/{old['id']}/upgrade", json={"tier": "pro"}, headers=ADMIN)
    assert r.status_code == 409
    assert {k["id"]: k["tier"] for k in _keys(client, project)}[old["id"]] == "free"
