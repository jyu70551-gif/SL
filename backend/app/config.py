import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
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


# ---------------------------------------------------------------------------
# AI 설정 (docs/sdd-ai.md 4장). 키만 backend/.env 에 넣으면 켜집니다. 나머지는 기본값이 있습니다.
# ---------------------------------------------------------------------------

# 키를 읽는 .env 파일. 시험에서는 None 으로 바꿔서 실제 .env 를 읽지 않게 합니다.
AI_ENV_FILE: Path | None = BASE_DIR / ".env"

# OPENAI_MODEL 이 비어 있으면, 이 키로 쓸 수 있는 모델 중 아래에서 가장 앞의 것을 자동으로 고릅니다.
# (모델 이름은 계속 바뀌므로 코드에 하나를 박아 두지 않습니다)
AI_MODEL_CANDIDATES = ["gpt-5.4-mini", "gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini"]


@dataclass(frozen=True)
class AiSettings:
    enabled: bool = True
    model: str = ""  # 빈 값 = 자동 선택
    timeout_seconds: float = 20.0
    max_retries: int = 1
    monthly_call_limit: int = 300
    max_items: int = 2
    note_max_chars: int = 500
    problems: tuple[str, ...] = ()  # 잘못된 값 안내. AI 기능만 기본값으로 돌리고 서버는 멈추지 않습니다.


def _parse_number(values, key, default, cast, low, problems):
    raw = (values.get(key) or "").strip()
    if not raw:
        return default
    try:
        number = cast(raw)
    except ValueError:
        problems.append(f"{key} 값은 숫자여야 해요. 지금은 기본값 {default}을(를) 씁니다.")
        return default
    if number < low:
        problems.append(f"{key} 값은 {low} 이상이어야 해요. 지금은 기본값 {default}을(를) 씁니다.")
        return default
    return number


def get_ai_settings(values=None) -> AiSettings:
    """환경 변수에서 AI 설정을 읽습니다. 값이 이상해도 예외 대신 problems 에 담아 기본값으로 돌립니다."""
    values = os.environ if values is None else values
    problems: list[str] = []
    enabled_raw = (values.get("AI_ENABLED") or "true").strip().lower()
    if enabled_raw not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        problems.append("AI_ENABLED 값은 true 또는 false 여야 해요. 지금은 true 로 봅니다.")
        enabled_raw = "true"
    return AiSettings(
        enabled=enabled_raw in {"true", "1", "yes", "on"},
        model=(values.get("OPENAI_MODEL") or "").strip(),
        timeout_seconds=_parse_number(values, "AI_TIMEOUT_SECONDS", 20.0, float, 1, problems),
        max_retries=_parse_number(values, "AI_MAX_RETRIES", 1, int, 0, problems),
        monthly_call_limit=_parse_number(values, "AI_MONTHLY_CALL_LIMIT", 300, int, 1, problems),
        max_items=_parse_number(values, "AI_BRIEFING_MAX_ITEMS", 2, int, 1, problems),
        note_max_chars=_parse_number(values, "AI_NOTE_MAX_CHARS", 500, int, 20, problems),
        problems=tuple(problems),
    )


_key_cache: dict = {"path": None, "mtime": None, "key": ""}


def read_openai_key(env_file: Path | None) -> str:
    """OPENAI_API_KEY 를 읽습니다. .env 파일이 바뀌면(수정 시각 기준) 서버를 다시 켜지 않아도 새 값이 반영됩니다.

    우선순위: .env 파일 → 프로세스 환경 변수. 키 값은 로그나 화면에 내보내지 않습니다.
    """
    if env_file is not None:
        try:
            mtime = env_file.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is not None:
            if _key_cache["path"] != str(env_file) or _key_cache["mtime"] != mtime:
                _key_cache.update(
                    path=str(env_file),
                    mtime=mtime,
                    key=(dotenv_values(env_file).get("OPENAI_API_KEY") or "").strip(),
                )
            if _key_cache["key"]:
                return _key_cache["key"]
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


_env_cache: dict[tuple[str, str], tuple[float | None, str]] = {}


def read_env_key(name: str, env_file: Path | None) -> str:
    """공식 일정 가져오기용 인증키(DATA_GO_KR_API_KEY, NEIS_API_KEY)를 읽습니다. read_openai_key 와 같은 방식이라
    .env 를 고치면 서버를 다시 켜지 않아도 반영됩니다. 키 값은 로그나 화면에 내보내지 않습니다."""
    if env_file is not None:
        try:
            mtime = env_file.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is not None:
            cached = _env_cache.get((str(env_file), name))
            if cached is None or cached[0] != mtime:
                cached = (mtime, (dotenv_values(env_file).get(name) or "").strip())
                _env_cache[(str(env_file), name)] = cached
            if cached[1]:
                return cached[1]
    return (os.environ.get(name) or "").strip()


def read_ai_settings(env_file: Path | None) -> AiSettings:
    """.env 파일의 AI_* 값을 우선하고, 없으면 환경 변수를 씁니다. (키와 마찬가지로 재시작 없이 반영)"""
    merged = dict(os.environ)
    if env_file is not None and env_file.exists():
        merged.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    return get_ai_settings(merged)
