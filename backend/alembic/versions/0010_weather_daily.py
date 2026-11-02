"""날짜별 실제 관측 날씨 (내일 예상 매출용)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_daily",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("station", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("avg_temp", sa.Float(), nullable=False),
        sa.Column("rain_mm", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("weather_daily")
