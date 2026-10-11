"""Uniqueness guarantees for concurrent writers (prompt versions, Pro key provisioning).

- prompt_versions: unique (project, prompt_name, version). Existing duplicates make the upgrade
  fail with the query that lists them, unless CORTEXOPS_RESEQUENCE_PROMPT_VERSIONS=1 is set, in
  which case every affected prompt is renumbered 1..n in (version, created_at, id) order.
  No row is deleted either way.
- api_keys.provision_ref: unique id of the payment event that minted a key, plus a partial unique
  index allowing one active provisioned Pro key per project.

Eval ingest needs no new constraint: eval_runs.id is the client run_id and already the primary key.

Revision ID: 0002_uniqueness
Revises: 0001_baseline
Create Date: 2026-10-09
"""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0002_uniqueness"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

RESEQUENCE_ENV = "CORTEXOPS_RESEQUENCE_PROMPT_VERSIONS"
PROMPT_VERSION_INDEX = "uq_prompt_versions_project_prompt_name_version"
PROVISION_REF_INDEX = "ix_api_keys_provision_ref"
PROVISIONED_PRO_INDEX = "uq_api_keys_provisioned_pro_project"
PROVISIONED_PRO_WHERE = {
    "postgresql_where": sa.text("provision_ref IS NOT NULL AND is_active AND tier = 'pro'"),
    "sqlite_where": sa.text("provision_ref IS NOT NULL AND is_active = 1 AND tier = 'pro'"),
}

DUPLICATE_PROMPT_VERSIONS_SQL = (
    "SELECT project, prompt_name, version, COUNT(*) AS copies FROM prompt_versions "
    "GROUP BY project, prompt_name, version HAVING COUNT(*) > 1 ORDER BY project, prompt_name, version"
)


def _inspector() -> sa.Inspector | None:
    return None if context.is_offline_mode() else sa.inspect(op.get_bind())


def _has_column(insp: sa.Inspector | None, table: str, column: str) -> bool:
    return bool(insp) and any(c["name"] == column for c in insp.get_columns(table))


def _has_index(insp: sa.Inspector | None, table: str, name: str) -> bool:
    return bool(insp) and any(ix["name"] == name for ix in insp.get_indexes(table))


def _resequence_prompt_versions(bind, duplicates) -> None:
    prompts = {(row.project, row.prompt_name) for row in duplicates}
    for project, prompt_name in sorted(prompts):
        rows = bind.execute(
            sa.text(
                "SELECT id, version FROM prompt_versions WHERE project = :project AND prompt_name = :prompt_name "
                "ORDER BY version, created_at, id"
            ),
            {"project": project, "prompt_name": prompt_name},
        ).all()
        for new_version, row in enumerate(rows, start=1):
            if row.version != new_version:
                log.warning(
                    "prompt_versions %s: %s/%s v%s -> v%s", row.id, project, prompt_name, row.version, new_version,
                )
                bind.execute(
                    sa.text("UPDATE prompt_versions SET version = :version WHERE id = :id"),
                    {"version": new_version, "id": row.id},
                )


def _check_prompt_version_duplicates() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(sa.text(DUPLICATE_PROMPT_VERSIONS_SQL)).all()
    if not duplicates:
        return
    listing = "; ".join(f"{d.project}/{d.prompt_name} v{d.version} x{d.copies}" for d in duplicates[:20])
    if os.environ.get(RESEQUENCE_ENV) == "1":
        log.warning("Resequencing %d duplicated prompt versions: %s", len(duplicates), listing)
        _resequence_prompt_versions(bind, duplicates)
        return
    raise RuntimeError(
        f"prompt_versions has {len(duplicates)} duplicated (project, prompt_name, version) groups "
        f"[{listing}]. Find them with:\n  {DUPLICATE_PROMPT_VERSIONS_SQL};\n"
        f"Resolve them by hand, or re-run with {RESEQUENCE_ENV}=1 to renumber each affected prompt "
        "1..n in (version, created_at, id) order (no rows are deleted). See docs/migrations.md."
    )


def upgrade() -> None:
    insp = _inspector()

    if not _has_index(insp, "prompt_versions", PROMPT_VERSION_INDEX):
        if insp is not None:
            _check_prompt_version_duplicates()
        op.create_index(
            PROMPT_VERSION_INDEX, "prompt_versions", ["project", "prompt_name", "version"], unique=True,
        )

    if not _has_column(insp, "api_keys", "provision_ref"):
        op.add_column("api_keys", sa.Column("provision_ref", sa.String(length=255), nullable=True))
    if not _has_index(insp, "api_keys", PROVISION_REF_INDEX):
        op.create_index(op.f(PROVISION_REF_INDEX), "api_keys", ["provision_ref"], unique=True)
    if not _has_index(insp, "api_keys", PROVISIONED_PRO_INDEX):
        op.create_index(PROVISIONED_PRO_INDEX, "api_keys", ["project"], unique=True, **PROVISIONED_PRO_WHERE)


def downgrade() -> None:
    op.drop_index(PROVISIONED_PRO_INDEX, table_name="api_keys", **PROVISIONED_PRO_WHERE)
    op.drop_index(op.f(PROVISION_REF_INDEX), table_name="api_keys")
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("provision_ref")
    op.drop_index(PROMPT_VERSION_INDEX, table_name="prompt_versions")
