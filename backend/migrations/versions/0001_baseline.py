"""Baseline: the schema that Base.metadata.create_all() produced before Alembic (v0.5.1).

Safe on databases that already have these tables (production was built with create_all):
existing tables are left untouched after checking they have every baseline column, and only
missing tables and indexes are created. On such databases `alembic stamp 0001_baseline` is
equivalent; see docs/migrations.md.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-09
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _projects() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("projects_pkey")),
    ]


def _api_keys() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project", sa.String(length=255), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project"], ["projects.name"], name=op.f("api_keys_project_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("api_keys_pkey")),
    ]


def _eval_runs() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project", sa.String(length=255), nullable=False),
        sa.Column("dataset_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.Integer(), nullable=False),
        sa.Column("task_completion_rate", sa.Float(), nullable=False),
        sa.Column("tool_accuracy", sa.Float(), nullable=False),
        sa.Column("latency_p50_ms", sa.Float(), nullable=False),
        sa.Column("latency_p95_ms", sa.Float(), nullable=False),
        sa.Column("regressions", sa.Integer(), nullable=False),
        sa.Column("baseline_run_id", sa.String(length=36), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("raw_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project"], ["projects.name"], name=op.f("eval_runs_project_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("eval_runs_pkey")),
    ]


def _case_results() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=255), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("task_completion", sa.Boolean(), nullable=False),
        sa.Column("tool_accuracy", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("failure_kind", sa.String(length=50), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], name=op.f("case_results_run_id_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("case_results_pkey")),
    ]


def _traces() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project", sa.String(length=255), nullable=False),
        sa.Column("case_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_latency_ms", sa.Float(), nullable=False),
        sa.Column("failure_kind", sa.String(length=50), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("raw_trace", sa.Text(), nullable=False),
        sa.Column("environment", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project"], ["projects.name"], name=op.f("traces_project_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("traces_pkey")),
    ]


def _prompt_versions() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project", sa.String(length=255), nullable=False),
        sa.Column("prompt_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("commit_message", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["prompt_versions.id"], name=op.f("prompt_versions_parent_version_id_fkey"),
        ),
        sa.ForeignKeyConstraint(["project"], ["projects.name"], name=op.f("prompt_versions_project_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("prompt_versions_pkey")),
    ]


def _eval_datasets() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("cases", sa.Text(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project"], ["projects.name"], name=op.f("eval_datasets_project_fkey")),
        sa.PrimaryKeyConstraint("id", name=op.f("eval_datasets_pkey")),
    ]


def _auth_audit_logs() -> list:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("project", sa.String(length=255), nullable=True),
        sa.Column("key_id", sa.String(length=36), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("auth_audit_logs_pkey")),
    ]


# (table, column factory, [(index columns, unique)]) in foreign-key dependency order.
TABLES: list[tuple[str, Callable[[], list], list[tuple[list[str], bool]]]] = [
    ("projects", _projects, [(["name"], True)]),
    ("api_keys", _api_keys, [(["key_hash"], True), (["project"], False), (["tier"], False)]),
    ("eval_runs", _eval_runs, [(["project"], False), (["status"], False)]),
    ("case_results", _case_results, [(["run_id"], False)]),
    ("traces", _traces, [(["created_at"], False), (["project"], False)]),
    ("prompt_versions", _prompt_versions, [(["created_at"], False), (["project"], False), (["prompt_name"], False)]),
    ("eval_datasets", _eval_datasets, [(["created_at"], False), (["name"], False), (["project"], False)]),
    ("auth_audit_logs", _auth_audit_logs, [
        (["created_at"], False), (["event"], False), (["key_id"], False), (["outcome"], False), (["project"], False),
    ]),
]


def _index_name(table: str, columns: list[str]) -> str:
    return f"ix_{table}_{'_'.join(columns)}"


def upgrade() -> None:
    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names()) if inspector else set()

    for table, columns, indexes in TABLES:
        if table not in existing_tables:
            op.create_table(table, *columns())
            for cols, unique in indexes:
                op.create_index(op.f(_index_name(table, cols)), table, cols, unique=unique)
            continue

        expected = [c.name for c in columns() if isinstance(c, sa.Column)]
        present = {c["name"] for c in inspector.get_columns(table)}
        missing = [name for name in expected if name not in present]
        if missing:
            raise RuntimeError(
                f"Table {table!r} already exists but lacks baseline columns {missing}. "
                "Add them to match backend/app/models/records.py (v0.5.1) before upgrading; "
                "see docs/migrations.md, 'Adopting an existing database'."
            )
        present_indexes = {ix["name"] for ix in inspector.get_indexes(table)}
        for cols, unique in indexes:
            name = _index_name(table, cols)
            if name not in present_indexes:
                op.create_index(op.f(name), table, cols, unique=unique)


def downgrade() -> None:
    raise RuntimeError(
        "Refusing to downgrade past the baseline: it would drop every CortexOps table. "
        "Restore from a backup instead (docs/migrations.md, 'Rollback')."
    )
