"""LLM-as-judge cost and token usage per eval run and per case (all nullable).

Revision ID: 0003_eval_cost
Revises: 0002_uniqueness
Create Date: 2026-10-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0003_eval_cost"
down_revision: str | None = "0002_uniqueness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("eval_runs", "case_results")


def _columns() -> list[sa.Column]:
    return [
        sa.Column("judge_cost_usd", sa.Float(), nullable=True),
        sa.Column("judge_tokens_in", sa.Integer(), nullable=True),
        sa.Column("judge_tokens_out", sa.Integer(), nullable=True),
    ]


def upgrade() -> None:
    insp = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    for table in TABLES:
        present = {c["name"] for c in insp.get_columns(table)} if insp else set()
        for column in _columns():
            if column.name not in present:
                op.add_column(table, column)


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch_op:
            for column in reversed(_columns()):
                batch_op.drop_column(column.name)
