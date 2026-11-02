import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import URL

from app import address, anomalies, auth, config, forecast, holidays, home, markets, sales_detail, schools, suggestions, uploads, weather
from app import settings as settings_page  # create_app 안의 settings 변수와 이름이 겹치지 않게
from app.ai import router as ai_router
from app.ai.service import AiService
from app.config import MIN_PASSWORD_LENGTH, build_database_url, get_settings
from app.db import make_engine, make_session_factory, verify_connection, verify_migrated
from app.models import AuthState
from app.security import hash_password

logger = logging.getLogger("sl")


def seed_password(session_factory, initial_password: str) -> None:
    """비밀번호가 아직 없을 때만 .env의 INITIAL_PASSWORD로 처음 한 번 정합니다."""
    with session_factory() as db:
        if db.get(AuthState, 1) is not None:
            return
        if not initial_password:
            logger.warning(
                "비밀번호가 아직 정해지지 않았습니다. backend/.env 에 INITIAL_PASSWORD를 넣고 서버를 다시 켜 주세요."
            )
            return
        if len(initial_password) < MIN_PASSWORD_LENGTH:
            raise RuntimeError(
                f"INITIAL_PASSWORD는 {MIN_PASSWORD_LENGTH}글자 이상이어야 합니다. backend/.env 를 확인해 주세요."
            )
        db.add(AuthState(id=1, password_hash=hash_password(initial_password)))
        db.commit()


def create_app(database_url: str | URL | None = None, llm=None) -> FastAPI:
    """database_url은 시험에서만 직접 넘깁니다. 서비스는 backend/.env 의 DB_* 값을 씁니다."""
    settings = get_settings()
    if os.getenv("DATABASE_URL"):
        logger.warning(
            "backend/.env 의 DATABASE_URL 항목은 더 이상 쓰이지 않아요. DB_HOST 등 DB_* 항목을 채워 주세요."
        )

    # 데이터 주소 목록(문서 화면)을 바깥에 보여주지 않습니다.
    app = FastAPI(title="SL", docs_url=None, redoc_url=None, openapi_url=None)

    engine = make_engine(database_url if database_url is not None else build_database_url())
    verify_connection(engine)
    # 테이블은 서버가 만들지 않고 Alembic(alembic upgrade head)으로만 만듭니다.
    verify_migrated(engine)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    # AI: 키가 없으면 꺼진 상태로 정상 동작합니다. 키는 .env 에 넣으면 서버를 다시 켜지 않아도 반영됩니다.
    # llm 은 시험에서 가짜 LLM 을 넣을 때만 씁니다.
    app.state.ai = AiService(app.state.session_factory, llm=llm, env_file=config.AI_ENV_FILE)
    seed_password(app.state.session_factory, settings.initial_password)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # 랩(시연용 가짜 데이터) 서버일 때만 lab 표시가 붙습니다. 화면이 "시연용" 배너를 띄우는 데 씁니다. (tools/serve_lab.py)
    lab = os.getenv("SL_LAB_MODE") == "1"

    @app.get("/api/health")
    def health():
        return {"status": "ok", "lab": True} if lab else {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(uploads.router)
    app.include_router(home.router)
    app.include_router(anomalies.router)
    app.include_router(settings_page.router)
    app.include_router(schools.router)
    app.include_router(address.router)
    app.include_router(markets.router)
    app.include_router(holidays.router)
    app.include_router(weather.router)
    app.include_router(forecast.router)
    app.include_router(suggestions.router)
    app.include_router(sales_detail.router)
    app.include_router(ai_router.router)
    return app
