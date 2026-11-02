"""일정(방학 등)과 장날

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "schedule_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False, server_default="owner"),
    )
    op.create_index("ix_schedule_events_kind", "schedule_events", ["kind"])
    op.create_table(
        "market_days",
        sa.Column("day", sa.Integer(), primary_key=True, autoincrement=False),
    )


def downgrade() -> None:
    op.drop_table("market_days")
    op.drop_index("ix_schedule_events_kind", table_name="schedule_events")
    op.drop_table("schedule_events")
