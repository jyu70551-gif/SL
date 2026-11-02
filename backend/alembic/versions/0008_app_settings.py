"""설정 테이블 (알림 민감도)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=40), primary_key=True),
        sa.Column("value", sa.String(length=40), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
