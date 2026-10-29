import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# 비밀번호 규칙 (spec 1번, 7-2)
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 10
SESSION_DAYS = 30

DB_ENV_KEYS = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_SSLMODE"]


class DbConfigError(RuntimeError):
    """DB 설정(.env)이 없거나 잘못됐을 때. 메시지에는 비밀번호나 연결 문자열을 넣지 않습니다."""


@dataclass(frozen=True)
class Settings:
    initial_password: str
    frontend_origins: list[str]


def get_settings() -> Settings:
    origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173")
    return Settings(
        initial_password=os.getenv("INITIAL_PASSWORD", ""),
        frontend_origins=[o.strip() for o in origins.split(",") if o.strip()],
    )


def build_database_url() -> URL:
    """backend/.env 의 DB_* 값으로 Supabase(PostgreSQL) 접속 주소를 만듭니다.

    값이 없거나 이상하면 SQLite로 대신 연결하지 않고, 확인할 항목을 알려 주며 멈춥니다.
    """
    values = {key: os.getenv(key, "").strip() for key in DB_ENV_KEYS}
    problems: list[str] = []

    for key in ("DB_HOST", "DB_USER", "DB_PASSWORD"):
        if not values[key]:
            problems.append(f"{key} 값이 비어 있어요. backend/.env 에 직접 입력해 주세요.")

    host = values["DB_HOST"]
    if host and ("://" in host or "@" in host or "/" in host or " " in host):
        problems.append("DB_HOST에는 주소만 넣어 주세요. (postgresql:// 나 사용자 이름, 비밀번호는 넣지 않습니다)")

    port_text = values["DB_PORT"] or "5432"
    port = None
    if port_text.isdigit() and 0 < int(port_text) < 65536:
        port = int(port_text)
    else:
        problems.append("DB_PORT는 숫자여야 해요. Session pooler는 보통 5432입니다.")

    if problems:
        raise DbConfigError(
            "DB 설정을 확인해 주세요.\n  - "
            + "\n  - ".join(problems)
            + "\n(항목 설명은 backend/.env.example 을 보세요)"
        )

    return URL.create(
        drivername="postgresql+psycopg",
        username=values["DB_USER"],
        password=values["DB_PASSWORD"],
        host=host,
        port=port,
        database=values["DB_NAME"] or "postgres",
        query={"sslmode": values["DB_SSLMODE"] or "require"},
    )
