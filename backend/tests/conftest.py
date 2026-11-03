"""시험 공통 도구.

시험은 항상 임시 SQLite 파일에서만 돌아갑니다. 실제 .env 의 DB 값이 있어도 쓰지 않습니다.
"""
import pytest

from app import config
from app.db import Base, make_engine
from app.main import create_app


@pytest.fixture(autouse=True)
def _never_touch_real_database(monkeypatch):
    # backend/.env 가 불러와져 있어도 시험이 실제 DB에 닿지 않도록 DB 설정을 비웁니다.
    for key in ["DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_SSLMODE"]:
        monkeypatch.delenv(key, raising=False)
    # AI도 마찬가지: 실제 backend/.env 의 OpenAI 키를 시험이 읽거나 쓰지 않게 합니다. (시험은 가짜 LLM만 씁니다)
    for key in ["OPENAI_API_KEY", "OPENAI_MODEL", "AI_ENABLED", "AI_TIMEOUT_SECONDS", "AI_MAX_RETRIES",
                "AI_MONTHLY_CALL_LIMIT", "AI_BRIEFING_MAX_ITEMS", "AI_NOTE_MAX_CHARS"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "AI_ENV_FILE", None)
    # 공식 일정 가져오기 키도 마찬가지입니다. (시험은 가짜 응답만 씁니다)
    for key in ["DATA_GO_KR_API_KEY", "NEIS_API_KEY", "KAKAO_REST_API_KEY", "MARKET_API_KEY", "HOLIDAY_API_KEY", "WEATHER_PAST_API_KEY", "WEATHER_FORECAST_API_KEY", "WEATHER_WARNING_API_KEY", "STORE_API_KEY", "SGIS_ID", "SGIS_SECURITY_KEY"]:
        monkeypatch.delenv(key, raising=False)


def build_app(tmp_path, name="test.db", llm=None):
    """테이블이 만들어진 임시 SQLite 위에서 앱을 만듭니다. (실제 서비스는 Alembic으로 만듭니다)"""
    url = f"sqlite:///{tmp_path / name}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return create_app(database_url=url, llm=llm)
