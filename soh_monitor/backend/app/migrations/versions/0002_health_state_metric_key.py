"""health_states 에 metric_key 추가, 열린 장애 유일성 보장

Metric 단위 판정 결과와 분류 단위 집계를 한 표에 담기 위해 metric_key 를 추가한다.
집계 행은 metric_key 가 빈 문자열이다.

열린 장애 유일성은 부분 유일 인덱스로 DB 가 보장한다. 같은 원인으로 장애가 계속 새로
생기면 알림이 폭주하고 이력이 쓸모없어진다.

Revision ID: 0002_health_state_metric_key
Revises: 923da4aa4e08
Create Date: 2026-08-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_health_state_metric_key"
down_revision: Union[str, None] = "923da4aa4e08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("health_states", schema=None) as batch_op:
        # 이미 쌓인 행에는 분류 단위 집계라는 뜻으로 빈 문자열을 넣는다.
        # server_default 없이 NOT NULL 을 붙이면 기존 행이 있는 DB 에서 실패한다.
        batch_op.add_column(
            sa.Column("metric_key", sa.String(length=128), nullable=False, server_default="")
        )
        batch_op.drop_constraint(
            "uq_health_states_device_id_category_dimension_value", type_="unique"
        )
        batch_op.create_index(
            "ix_health_states_device_category", ["device_id", "category"], unique=False
        )
        batch_op.create_unique_constraint(
            "uq_health_states_device_id_category_metric_key_dimension_value",
            ["device_id", "category", "metric_key", "dimension_value"],
        )

    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.create_index(
            "uq_incidents_open_target",
            ["device_id", "category", "metric_key", "dimension_value"],
            unique=True,
            postgresql_where=sa.text("status <> 'RESOLVED'"),
            sqlite_where=sa.text("status <> 'RESOLVED'"),
        )


def downgrade() -> None:
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_incidents_open_target",
            postgresql_where=sa.text("status <> 'RESOLVED'"),
            sqlite_where=sa.text("status <> 'RESOLVED'"),
        )

    with op.batch_alter_table("health_states", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_health_states_device_id_category_metric_key_dimension_value", type_="unique"
        )
        batch_op.drop_index("ix_health_states_device_category")
        batch_op.create_unique_constraint(
            "uq_health_states_device_id_category_dimension_value",
            ["device_id", "category", "dimension_value"],
        )
        batch_op.drop_column("metric_key")
