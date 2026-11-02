"""AI 점검·초안 평가 테이블

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("ref", sa.String(length=80), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ai_feedback")
