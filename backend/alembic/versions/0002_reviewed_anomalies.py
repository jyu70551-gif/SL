"""확인함·정상 기록 테이블 추가

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reviewed_anomalies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("sales_date", sa.Date(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("category", "sales_date", name="uq_reviewed_category_date"),
    )
    op.create_index("ix_reviewed_anomalies_sales_date", "reviewed_anomalies", ["sales_date"])


def downgrade() -> None:
    op.drop_index("ix_reviewed_anomalies_sales_date", table_name="reviewed_anomalies")
    op.drop_table("reviewed_anomalies")
