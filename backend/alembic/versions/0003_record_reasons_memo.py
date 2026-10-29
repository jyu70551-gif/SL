"""운영 상황 기록에 선택 항목(reasons)과 메모(memo) 열 추가

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 이미 있는 기록은 빈 값("")이 됩니다. 기존 데이터는 바뀌지 않습니다.
    with op.batch_alter_table("reviewed_anomalies") as batch:
        batch.add_column(sa.Column("reasons", sa.String(length=255), nullable=False, server_default=""))
        batch.add_column(sa.Column("memo", sa.String(length=500), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("reviewed_anomalies") as batch:
        batch.drop_column("memo")
        batch.drop_column("reasons")
