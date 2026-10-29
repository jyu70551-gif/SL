"""시험 공통 도구.

시험은 항상 임시 SQLite 파일에서만 돌아갑니다. 실제 .env 의 DB 값이 있어도 쓰지 않습니다.
"""
import pytest

from app.db import Base, make_engine
from app.main import create_app


@pytest.fixture(autouse=True)
def _never_touch_real_database(monkeypatch):
    # backend/.env 가 불러와져 있어도 시험이 실제 DB에 닿지 않도록 DB 설정을 비웁니다.
    for key in ["DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_SSLMODE"]:
        monkeypatch.delenv(key, raising=False)


def build_app(tmp_path, name="test.db"):
    """테이블이 만들어진 임시 SQLite 위에서 앱을 만듭니다. (실제 서비스는 Alembic으로 만듭니다)"""
    url = f"sqlite:///{tmp_path / name}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return create_app(database_url=url)
