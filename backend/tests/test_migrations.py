"""Alembic migrations: models stay in sync, existing create_all() databases adopt cleanly, constraints apply.

Runs on a throwaway SQLite file; set CORTEXOPS_TEST_POSTGRES_URL=postgresql+asyncpg://.../<empty db>
to also run against Postgres (its public schema is wiped between tests).
"""
from __future__ import annotations

import asyncio
import io
import os
import uuid

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from app.db import Base
from app.migrate import SchemaNotCurrentError, alembic_config, assert_schema_current, upgrade_head_async
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

HEAD = "0003_eval_cost"


def _backends() -> list:
    params = ["sqlite"]
    if os.environ.get("CORTEXOPS_TEST_POSTGRES_URL"):
        params.append("postgresql")
    return params


@pytest.fixture(params=_backends())
def db_url(request, tmp_path):
    if request.param == "sqlite":
        yield f"sqlite+aiosqlite:///{tmp_path}/migrations.db"
        return
    url = os.environ["CORTEXOPS_TEST_POSTGRES_URL"]
    _execute(url, "DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
    yield url


async def _with_conn(url: str, fn):
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            return await fn(conn)
    finally:
        await engine.dispose()


def _execute(url: str, *statements: str, params: dict | None = None) -> None:
    async def run(conn):
        for stmt in statements:
            await conn.execute(text(stmt), params or {})
    asyncio.run(_with_conn(url, run))


def _rows(url: str, sql: str) -> list:
    async def run(conn):
        return (await conn.execute(text(sql))).all()
    return asyncio.run(_with_conn(url, run))


def _schema_diff(url: str) -> list:
    async def run(conn):
        return await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    return asyncio.run(_with_conn(url, run))


def _revision(url: str) -> set[str]:
    async def run(conn):
        return set(await conn.run_sync(lambda c: MigrationContext.configure(c).get_current_heads()))
    return asyncio.run(_with_conn(url, run))


def _cfg(url: str):
    cfg = alembic_config(url)
    cfg.attributes["configure_logger"] = False
    return cfg


def _upgrade(url: str, target: str = "head") -> None:
    command.upgrade(_cfg(url), target)


def _create_all(url: str) -> None:
    asyncio.run(_with_conn(url, lambda conn: conn.run_sync(Base.metadata.create_all)))


def _legacy_db(url: str) -> None:
    """A database as production has it: baseline tables created without Alembic."""
    _upgrade(url, "0001_baseline")
    _execute(url, "DROP TABLE alembic_version")


def _insert_prompt_version(url: str, project: str, name: str, version: int, created_at: str) -> str:
    row_id = str(uuid.uuid4())
    _execute(
        url,
        "INSERT INTO prompt_versions (id, project, prompt_name, version, content, model, temperature, "
        "commit_message, author, created_at) VALUES (:id, :project, :name, :version, 'c', '', 0.7, '', '', "
        f"'{created_at}')",
        params={"id": row_id, "project": project, "name": name, "version": version},
    )
    return row_id


def _ensure_project(url: str, project: str) -> None:
    _execute(url, "INSERT INTO projects (id, name, description) VALUES (:id, :name, '')",
             params={"id": str(uuid.uuid4()), "name": project})


def test_fresh_database_matches_models(db_url):
    _upgrade(db_url)
    assert _revision(db_url) == {HEAD}
    assert _schema_diff(db_url) == []


def test_downgrade_to_baseline_and_back(db_url):
    _upgrade(db_url)
    command.downgrade(_cfg(db_url), "0001_baseline")
    assert _revision(db_url) == {"0001_baseline"}
    _upgrade(db_url)
    assert _schema_diff(db_url) == []


def test_baseline_refuses_downgrade(db_url):
    _upgrade(db_url, "0001_baseline")
    with pytest.raises(RuntimeError, match="Refusing to downgrade past the baseline"):
        command.downgrade(_cfg(db_url), "base")


def test_existing_database_upgrades_without_stamp(db_url):
    _legacy_db(db_url)
    _ensure_project(db_url, "acme")
    _upgrade(db_url)
    assert _revision(db_url) == {HEAD}
    assert _schema_diff(db_url) == []
    assert [r.name for r in _rows(db_url, "SELECT name FROM projects")] == ["acme"]


def test_existing_database_stamp_then_upgrade(db_url):
    _legacy_db(db_url)
    command.stamp(_cfg(db_url), "0001_baseline")
    _upgrade(db_url)
    assert _revision(db_url) == {HEAD}
    assert _schema_diff(db_url) == []


def test_create_all_database_from_current_models_upgrades(db_url):
    _create_all(db_url)
    _upgrade(db_url)
    assert _revision(db_url) == {HEAD}
    assert _schema_diff(db_url) == []


def test_baseline_rejects_existing_table_missing_columns(db_url):
    _execute(db_url, "CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL)")
    with pytest.raises(RuntimeError, match=r"lacks baseline columns \['description', 'created_at'\]"):
        _upgrade(db_url)


def test_duplicate_prompt_versions_block_upgrade_with_query(db_url):
    _upgrade(db_url, "0001_baseline")
    _ensure_project(db_url, "acme")
    _insert_prompt_version(db_url, "acme", "refund", 1, "2026-01-01 00:00:00")
    _insert_prompt_version(db_url, "acme", "refund", 1, "2026-01-02 00:00:00")

    with pytest.raises(RuntimeError) as exc:
        _upgrade(db_url)
    message = str(exc.value)
    assert "acme/refund v1 x2" in message
    assert "HAVING COUNT(*) > 1" in message
    assert "CORTEXOPS_RESEQUENCE_PROMPT_VERSIONS=1" in message
    assert _revision(db_url) == {"0001_baseline"}
    assert len(_rows(db_url, "SELECT id FROM prompt_versions")) == 2


def test_duplicate_prompt_versions_resequenced_on_opt_in(db_url, monkeypatch):
    _upgrade(db_url, "0001_baseline")
    _ensure_project(db_url, "acme")
    first = _insert_prompt_version(db_url, "acme", "refund", 1, "2026-01-01 00:00:00")
    racer = _insert_prompt_version(db_url, "acme", "refund", 1, "2026-01-02 00:00:00")
    later = _insert_prompt_version(db_url, "acme", "refund", 2, "2026-01-03 00:00:00")
    other = _insert_prompt_version(db_url, "acme", "triage", 1, "2026-01-01 00:00:00")

    monkeypatch.setenv("CORTEXOPS_RESEQUENCE_PROMPT_VERSIONS", "1")
    _upgrade(db_url)

    versions = {r.id: r.version for r in _rows(db_url, "SELECT id, version FROM prompt_versions")}
    assert versions == {first: 1, racer: 2, later: 3, other: 1}
    assert _schema_diff(db_url) == []


def test_assert_schema_current(db_url):
    async def check():
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            await assert_schema_current(engine)
        finally:
            await engine.dispose()

    _upgrade(db_url, "0002_uniqueness")
    with pytest.raises(SchemaNotCurrentError, match="0002_uniqueness"):
        asyncio.run(check())
    _upgrade(db_url)
    asyncio.run(check())


def test_startup_upgrade_runs_from_inside_an_event_loop(db_url):
    async def startup():
        await upgrade_head_async(db_url)  # env.py drives its own loop; must not clash with the app's

    asyncio.run(startup())
    assert _revision(db_url) == {HEAD}


def test_offline_sql_for_postgres():
    cfg = _cfg("postgresql+asyncpg://user@localhost/cortexops")
    buf = io.StringIO()
    cfg.output_buffer = buf
    command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE api_keys" in sql
    assert "CREATE UNIQUE INDEX uq_prompt_versions_project_prompt_name_version" in sql
    assert ("CREATE UNIQUE INDEX uq_api_keys_provisioned_pro_project ON api_keys (project) "
            "WHERE provision_ref IS NOT NULL AND is_active AND tier = 'pro'") in sql
    assert "ALTER TABLE eval_runs ADD COLUMN judge_cost_usd FLOAT" in sql
    assert f"UPDATE alembic_version SET version_num='{HEAD}'" in sql
