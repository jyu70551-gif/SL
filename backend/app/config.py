import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

# 비밀번호 규칙 (spec 1번, 7-2)
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 10
SESSION_DAYS = 30


@dataclass(frozen=True)
class Settings:
    database_url: str
    initial_password: str
    frontend_origins: list[str]


def get_settings() -> Settings:
    origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173")
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'sl_dev.db'}"),
        initial_password=os.getenv("INITIAL_PASSWORD", ""),
        frontend_origins=[o.strip() for o in origins.split(",") if o.strip()],
    )
