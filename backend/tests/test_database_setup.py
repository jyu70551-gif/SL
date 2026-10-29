"""Supabase(PostgreSQL) 전환 준비 확인.

실제 Supabase에는 연결하지 않습니다. 설정 검사, 안내 문구, Alembic 변경 기록이
SQLite와 PostgreSQL 문법 양쪽에서 맞는지만 확인합니다.
시험에 쓰인 비밀번호는 모두 가짜 값입니다.
"""
import io
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.config import DbConfigError, build_database_url
from app.db import Base, DbConnectionError, DbNotMigratedError, make_engine
from app.main import create_app

BACKEND = Path(__file__).resolve().parent.parent
SECRET = "super-secret-pw-xyz"


def set_db_env(monkeypatch, **overrides):
    values = {
        "DB_HOST": "aws-0-ap-northeast-2.pooler.supabase.com",
        "DB_USER": "postgres.testproject",
        "DB_PASSWORD": SECRET,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def alembic_config() -> Config:
    return Config(str(BACKEND / "alembic.ini"))


# --- .env 설정 검사 -------------------------------------------------------------------------


def test_missing_db_settings_stop_with_a_checklist_and_never_use_sqlite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DbConfigError) as error:
        create_app()
    message = str(error.value)
    for key in ("DB_HOST", "DB_USER", "DB_PASSWORD"):
        assert key in message
    assert ".env.example" in message
    # SQLite 파일이 몰래 만들어지지 않는다.
    assert list(tmp_path.iterdir()) == []


def test_old_sqlite_database_url_is_ignored_not_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'old.db'}")
    with pytest.raises(DbConfigError):
        create_app()
    assert not (tmp_path / "old.db").exists()


@pytest.mark.parametrize(
    "bad_host", ["postgresql://user:pw@host/db", "user@host.example.com", "host.example.com/postgres", "a b"]
)
def test_host_that_looks_like_a_connection_string_is_refused(monkeypatch, bad_host):
    set_db_env(monkeypatch, DB_HOST=bad_host)
    with pytest.raises(DbConfigError) as error:
        build_database_url()
    assert "DB_HOST" in str(error.value)
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("bad_port", ["abc", "0", "70000", "54 32"])
def test_port_must_be_a_number(monkeypatch, bad_port):
    set_db_env(monkeypatch, DB_PORT=bad_port)
    with pytest.raises(DbConfigError) as error:
        build_database_url()
    assert "DB_PORT" in str(error.value)


def test_url_is_built_from_separate_values_and_keeps_special_characters(monkeypatch):
    tricky = "p@ss:w/rd#1 ?"
    set_db_env(monkeypatch, DB_PASSWORD=tricky)
    url = build_database_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "aws-0-ap-northeast-2.pooler.supabase.com"
    assert url.port == 5432  # 값이 없으면 Session pooler 기본값
    assert url.database == "postgres"
    assert url.username == "postgres.testproject"
    assert url.password == tricky
    assert url.query["sslmode"] == "require"
    # 화면이나 로그에 찍혀도 비밀번호는 가려진다.
    assert tricky not in str(url) and tricky not in repr(url)


def test_wrong_connection_values_give_a_checklist_without_secrets(monkeypatch):
    set_db_env(monkeypatch, DB_HOST="127.0.0.1", DB_PORT="1")  # 아무도 듣지 않는 포트
    with pytest.raises(DbConnectionError) as error:
        create_app()
    message = str(error.value)
    assert "DB에 연결하지 못했어요" in message
    for key in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_PORT"):
        assert key in message
    assert SECRET not in message
    assert "127.0.0.1" not in message and "postgres.testproject" not in message


def test_tables_missing_asks_to_run_alembic(tmp_path):
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    with pytest.raises(DbNotMigratedError) as error:
        create_app(database_url=url)
    assert "alembic upgrade head" in str(error.value)


def test_server_does_not_create_tables_by_itself(tmp_path):
    url = f"sqlite:///{tmp_path / 'untouched.db'}"
    with pytest.raises(DbNotMigratedError):
        create_app(database_url=url)
    assert inspect(make_engine(url)).get_table_names() == []


# --- Alembic ------------------------------------------------------------------------------


def run_upgrade(url, revision="head"):
    engine = make_engine(url)
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)
    return engine


def test_one_command_creates_all_tables_and_matches_the_models(tmp_path):
    engine = run_upgrade(f"sqlite:///{tmp_path / 'm.db'}")
    names = set(inspect(engine).get_table_names())
    assert {"auth_state", "auth_sessions", "sales_uploads", "daily_sales", "alembic_version"} <= names
    with engine.connect() as conn:
        # 변경 기록과 모델(models.py)이 어긋나지 않는다.
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0001"


def test_running_it_again_does_not_apply_changes_twice(tmp_path):
    url = f"sqlite:///{tmp_path / 'again.db'}"
    engine = run_upgrade(url)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO auth_state (id, password_hash, failed_count) VALUES (1, 'x', 0)")
        )
    run_upgrade(url)  # 한 번 더 실행해도 오류가 없고
    with engine.connect() as conn:
        # 데이터도 그대로이며, 기록은 한 줄뿐이다.
        assert conn.execute(text("SELECT count(*) FROM auth_state")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM alembic_version")).scalar() == 1


def test_server_starts_on_tables_made_by_alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'ready.db'}"
    run_upgrade(url)
    monkeypatch.setenv("INITIAL_PASSWORD", "test-password-123")
    app = create_app(database_url=url)
    with app.state.session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM auth_state")).scalar() == 1


def test_postgresql_sql_preview_has_the_expected_tables():
    """연결 없이 PostgreSQL용 SQL만 만들어서, PostgreSQL 문법으로도 표가 만들어지는지 봅니다."""
    cfg = alembic_config()
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    sql = cfg.output_buffer.getvalue()
    for table in ("auth_state", "auth_sessions", "sales_uploads", "daily_sales"):
        assert f"CREATE TABLE {table}" in sql
    assert "SERIAL" in sql  # 자동으로 늘어나는 번호
    assert "BIGINT" in sql  # 판매액
    assert "TIMESTAMP WITHOUT TIME ZONE" in sql
    assert "CREATE UNIQUE INDEX ix_sales_uploads_sales_date" in sql
    assert "CREATE UNIQUE INDEX ix_auth_sessions_token_hash" in sql
    assert "INSERT INTO alembic_version" in sql
