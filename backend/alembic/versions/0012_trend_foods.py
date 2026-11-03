"""요즘 뜨는 식품: 식품·콘텐츠·언급·수집 상태·AI 설명·관심 식품

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trend_foods",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("brand", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("aliases", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="type"),
    )
    op.create_table(
        "trend_contents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="post"),
        sa.Column("url", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_key", sa.String(length=64), nullable=True),
        sa.Column("dedupe_key", sa.String(length=40), nullable=False),
        sa.Column("is_repost", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_ad", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("source", "source_id", name="uq_trend_content_source"),
    )
    op.create_index("ix_trend_contents_source", "trend_contents", ["source"])
    op.create_index("ix_trend_contents_dedupe_key", "trend_contents", ["dedupe_key"])
    op.create_table(
        "trend_mentions",
        sa.Column("content_id", sa.Integer(), primary_key=True),
        sa.Column("food_id", sa.Integer(), primary_key=True),
    )
    op.create_table(
        "trend_collections",
        sa.Column("source", sa.String(length=20), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "trend_explanations",
        sa.Column("food_id", sa.Integer(), primary_key=True),
        sa.Column("period_end", sa.Date(), primary_key=True),
        sa.Column("evidence_hash", sa.String(length=40), nullable=False),
        sa.Column("content_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("prompt_version", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.String(length=40), nullable=False, server_default=""),
    )
    op.create_table(
        "trend_favorites",
        sa.Column("food_id", sa.Integer(), primary_key=True),
        sa.Column("saved_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for name in ("trend_favorites", "trend_explanations", "trend_collections", "trend_mentions"):
        op.drop_table(name)
    op.drop_index("ix_trend_contents_dedupe_key", table_name="trend_contents")
    op.drop_index("ix_trend_contents_source", table_name="trend_contents")
    op.drop_table("trend_contents")
    op.drop_table("trend_foods")
