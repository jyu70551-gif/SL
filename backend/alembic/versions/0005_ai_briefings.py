"""오늘의 점검(AI 점검) 결과 테이블

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_briefings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sales_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("mode", sa.String(length=5), nullable=False, server_default="fixed"),
        sa.Column("facts_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payload", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_briefings_sales_date", "ai_briefings", ["sales_date"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ai_briefings_sales_date", table_name="ai_briefings")
    op.drop_table("ai_briefings")
