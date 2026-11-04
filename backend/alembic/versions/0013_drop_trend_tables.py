"""요즘 뜨는 식품: 옛 방식(14일 비교 순위)의 표 6개 삭제

화면이 버튼 한 번으로 오늘 결과를 보여 주는 방식("오늘 보기")으로 바뀌어 이 표들을 쓰지 않습니다. 오늘 결과는 설정 표(app_settings) 한 줄에 저장합니다.
0012 로 만든 표는 시연이 아닌 실제 서버에서는 비어 있어서 지워도 잃는 자료가 없습니다. 표가 이미 없으면 건너뜁니다.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04
"""
import importlib.util
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 만든 순서의 반대로 지웁니다
TABLES = ["trend_favorites", "trend_explanations", "trend_collections", "trend_mentions", "trend_contents", "trend_foods"]


def upgrade() -> None:
    for name in TABLES:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {name}"))  # 연결 없이 SQL만 만들 때(--sql)도 쓸 수 있고, 표가 없으면 건너뜁니다


def downgrade() -> None:
    # 0012 가 만들던 표를 그대로 다시 만듭니다
    spec = importlib.util.spec_from_file_location("migration_0012", Path(__file__).with_name("0012_trend_foods.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()
