"""상품별 하루 입출고 (소진율·폐기율·증량 검토 신호용)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_daily",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("product_code", sa.String(length=20), primary_key=True),
        sa.Column("name", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("opening", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discarded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("returned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closing", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("promo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sold_out_hour", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("stock_daily")
