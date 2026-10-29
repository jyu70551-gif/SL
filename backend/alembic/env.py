"""Alembic 실행 환경. 접속 정보는 backend/.env 의 DB_* 값에서만 읽고, 어디에도 출력하지 않습니다."""
from logging.config import fileConfig

from alembic import context

import app.models  # noqa: F401  (테이블 정의를 불러옵니다)
from app.config import DbConfigError, build_database_url
from app.db import Base, DbConnectionError, make_engine, verify_connection

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """미리보기용(--sql): DB에 연결하지 않고 PostgreSQL용 SQL만 출력합니다. 접속 정보는 쓰지 않습니다."""
    context.configure(
        url="postgresql+psycopg://",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 시험에서는 이미 열린 연결을 넘겨받습니다.
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    try:
        engine = make_engine(build_database_url())
        verify_connection(engine)
    except (DbConfigError, DbConnectionError) as error:
        # 긴 오류 기록 대신 확인할 항목만 보여주고 멈춥니다.
        raise SystemExit(f"\n{error}\n") from None
    try:
        # 한 번에 전부 적용되거나, 실패하면 아무것도 적용되지 않습니다.
        with engine.begin() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
