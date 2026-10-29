from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

REQUIRED_TABLES = ["auth_state", "reviewed_anomalies"]  # 가장 최근에 추가한 테이블까지 확인합니다

CONNECTION_CHECKLIST = [
    "DB_HOST: Supabase의 Connect 화면에서 'Session pooler' 항목의 주소(…pooler.supabase.com)인지",
    "DB_USER: 'postgres.프로젝트ID' 형태인지 (그냥 postgres가 아닙니다)",
    "DB_PASSWORD: 프로젝트를 만들 때 정한 '데이터베이스 비밀번호'인지 (SL 사용 비밀번호나 Supabase 계정 비밀번호가 아닙니다)",
    "DB_PORT: Session pooler는 5432인지",
    "Supabase 프로젝트가 일시 중지(Paused)되지 않았는지",
    "인터넷 연결과 방화벽",
]


class DbConnectionError(RuntimeError):
    """DB에 연결하지 못했을 때. 연결 문자열이나 비밀번호는 메시지에 넣지 않습니다."""


class DbNotMigratedError(RuntimeError):
    """연결은 됐지만 테이블이 아직 없을 때."""


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | URL) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        # 시험용. 서비스는 SQLite로 자동 연결하지 않습니다 (config.build_database_url 참고).
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        pool_pre_ping=True,  # 오래 놀던 연결이 끊겨 있어도 다시 이어 붙입니다.
        # Supabase pooler와 함께 써도 문제없도록 미리 준비된 문장(prepared statement)을 끕니다.
        # 주소가 틀렸을 때 몇 분씩 멈춰 있지 않고 10초 안에 안내가 나오게 합니다.
        connect_args={"prepare_threshold": None, "connect_timeout": 10},
    )


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _hint_for(error: Exception) -> str:
    # 원문 오류에는 주소 같은 정보가 섞일 수 있어 그대로 보여주지 않고, 종류만 알려 줍니다.
    raw = str(error).lower()
    if "password authentication failed" in raw or "authentication failed" in raw:
        return "사용자 이름(DB_USER) 또는 데이터베이스 비밀번호(DB_PASSWORD)가 맞지 않는 것 같아요."
    if "tenant or user not found" in raw:
        return "DB_USER가 'postgres.프로젝트ID' 형태가 맞는지, 프로젝트 ID가 맞는지 확인해 주세요."
    if "could not translate host" in raw or "name or service not known" in raw or "getaddrinfo" in raw:
        return "DB_HOST 주소를 찾을 수 없어요. 철자와 Session pooler 주소인지 확인해 주세요."
    if "timeout" in raw or "timed out" in raw:
        return "응답이 없어요. 인터넷 연결, 방화벽, 프로젝트 일시 중지 여부를 확인해 주세요."
    if "connection refused" in raw or "refused" in raw:
        return "연결이 거절됐어요. DB_HOST와 DB_PORT를 확인해 주세요."
    return "원인을 특정하지 못했어요."


def verify_connection(engine: Engine) -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise DbConnectionError(
            "DB에 연결하지 못했어요. "
            + _hint_for(error)
            + "\n확인할 것:\n  - "
            + "\n  - ".join(CONNECTION_CHECKLIST)
        ) from None


def verify_migrated(engine: Engine) -> None:
    inspector = inspect(engine)
    ready = all(inspector.has_table(name) for name in REQUIRED_TABLES) and "reasons" in {
        c["name"] for c in inspector.get_columns("reviewed_anomalies")
    }
    if not ready:
        raise DbNotMigratedError(
            "DB에는 연결됐지만 필요한 테이블이나 열이 아직 없어요(새로 추가된 항목이 있을 수 있어요). backend 폴더에서 "
            "'python -m alembic upgrade head' 를 먼저 실행해 주세요."
        )
