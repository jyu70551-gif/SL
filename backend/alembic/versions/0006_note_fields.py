"""운영 상황 기록에 AI 초안 정보 열 추가 (출처, 점주 원문, 시각, 초안 수정 여부)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 이미 있는 기록은 source='form'(직접 선택)이 되고 나머지는 빈 값입니다. 기존 데이터는 바뀌지 않습니다.
    with op.batch_alter_table("reviewed_anomalies") as batch:
        batch.add_column(sa.Column("source", sa.String(length=8), nullable=False, server_default="form"))
        batch.add_column(sa.Column("raw_text", sa.String(length=500), nullable=False, server_default=""))
        batch.add_column(sa.Column("time_hint", sa.String(length=30), nullable=False, server_default=""))
        batch.add_column(sa.Column("ai_edited", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("reviewed_anomalies") as batch:
        batch.drop_column("ai_edited")
        batch.drop_column("time_hint")
        batch.drop_column("raw_text")
        batch.drop_column("source")
