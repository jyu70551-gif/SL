"""처음 테이블 4개 만들기 (비밀번호·통행증·올린 파일·대분류별 매출)

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)

    op.create_table(
        "sales_uploads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sales_date", sa.Date(), nullable=False),
        sa.Column("cutoff_hour", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sales_uploads_sales_date", "sales_uploads", ["sales_date"], unique=True)

    op.create_table(
        "daily_sales",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sales_date", sa.Date(), nullable=False),
        sa.Column("product_code", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_daily_sales_sales_date", "daily_sales", ["sales_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_sales_sales_date", table_name="daily_sales")
    op.drop_table("daily_sales")
    op.drop_index("ix_sales_uploads_sales_date", table_name="sales_uploads")
    op.drop_table("sales_uploads")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("auth_state")
