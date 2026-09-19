"""adapter_metric_mappings 별칭 경로 유일 키

한 Metric 에 펌웨어별 원본 경로가 여러 개일 수 있다. 예전 유일 키는
canonical_metric_key 만 묶어 별칭 행을 거절했다.

Revision ID: 0005_adapter_mapping_source_path
Revises: 0004_edge_ingest_sequences
Create Date: 2026-09-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0005_adapter_mapping_source_path"
down_revision: Union[str, None] = "0004_edge_ingest_sequences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAME = (
    "uq_adapter_metric_mappings_adapter_key_adapter_version_"
    "firmware_range_canonical_metric_key_dimension_value"
)
NEW_NAME = (
    "uq_adapter_metric_mappings_adapter_key_adapter_version_"
    "firmware_range_source_path_canonical_metric_key_dimension_value"
)


def upgrade() -> None:
    with op.batch_alter_table("adapter_metric_mappings") as batch:
        batch.drop_constraint(OLD_NAME, type_="unique")
        batch.create_unique_constraint(
            NEW_NAME,
            [
                "adapter_key",
                "adapter_version",
                "firmware_range",
                "source_path",
                "canonical_metric_key",
                "dimension_value",
            ],
        )


def downgrade() -> None:
    with op.batch_alter_table("adapter_metric_mappings") as batch:
        batch.drop_constraint(NEW_NAME, type_="unique")
        batch.create_unique_constraint(
            OLD_NAME,
            [
                "adapter_key",
                "adapter_version",
                "firmware_range",
                "canonical_metric_key",
                "dimension_value",
            ],
        )
