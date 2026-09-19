"""edge_ingest_sequences 멱등 표와 인증서 폐기 시각

Revision ID: 0004_edge_ingest_sequences
Revises: 0003_edge_tasks
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_edge_ingest_sequences"
down_revision: Union[str, None] = "0003_edge_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "edge_ingest_sequences",
        sa.Column("edge_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("poll_id", sa.String(length=64), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["edge_id"],
            ["edge_collectors.id"],
            name=op.f("fk_edge_ingest_sequences_edge_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edge_ingest_sequences")),
        sa.UniqueConstraint("edge_id", "sequence", name="uq_edge_ingest_sequences_edge_id_sequence"),
    )
    with op.batch_alter_table("edge_collectors", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_incidents_open_edge",
        "incidents",
        ["edge_id", "category", "metric_key", "dimension_value"],
        unique=True,
        sqlite_where=sa.text("status <> 'RESOLVED' AND device_id IS NULL AND edge_id IS NOT NULL"),
        postgresql_where=sa.text("status <> 'RESOLVED' AND device_id IS NULL AND edge_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_incidents_open_edge", table_name="incidents")
    with op.batch_alter_table("edge_collectors", schema=None) as batch_op:
        batch_op.drop_column("revoked_at")
    op.drop_table("edge_ingest_sequences")
