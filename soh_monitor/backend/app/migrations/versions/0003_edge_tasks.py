"""edge_tasks 원격 작업 대기열

연결 시험처럼 지역망에서만 수행할 수 있는 일을 Edge 가 받아 간다.
중앙 API 프로세스가 관측소망으로 나가지 않기 위한 표다.

Revision ID: 0003_edge_tasks
Revises: 0002_health_state_metric_key
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_edge_tasks"
down_revision: Union[str, None] = "0002_health_state_metric_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "edge_tasks",
        sa.Column("edge_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "SUCCEEDED", "FAILED", name="edge_task_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name=op.f("fk_edge_tasks_device_id"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["edge_id"], ["edge_collectors.id"], name=op.f("fk_edge_tasks_edge_id"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edge_tasks")),
    )
    op.create_index("ix_edge_tasks_edge_status", "edge_tasks", ["edge_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_edge_tasks_edge_status", table_name="edge_tasks")
    op.drop_table("edge_tasks")
