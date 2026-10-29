from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import LOCK_MINUTES, MAX_FAILED_ATTEMPTS, SESSION_DAYS
from app.models import AuthSession, AuthState
from app.security import hash_token, new_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db(request: Request):
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


class LoginBody(BaseModel):
    password: str


def require_auth(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthSession:
    """데이터를 돌려주는 모든 주소는 이 확인을 거쳐야 합니다."""
    unauthorized = HTTPException(status_code=401, detail={"code": "unauthorized"})
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise unauthorized
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.expires_at > utcnow(),
        )
    )
    if session is None:
        raise unauthorized
    return session


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    now = utcnow()
    state = db.get(AuthState, 1)
    if state is None:
        raise HTTPException(status_code=503, detail={"code": "not_configured"})

    if state.locked_until is not None:
        if now < state.locked_until:
            retry = int((state.locked_until - now).total_seconds()) + 1
            raise HTTPException(
                status_code=429,
                detail={"code": "locked", "retry_after_seconds": retry},
            )
        state.locked_until = None
        state.failed_count = 0

    if not verify_password(body.password, state.password_hash):
        state.failed_count += 1
        if state.failed_count >= MAX_FAILED_ATTEMPTS:
            state.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            state.failed_count = 0
            db.commit()
            raise HTTPException(
                status_code=429,
                detail={"code": "locked", "retry_after_seconds": LOCK_MINUTES * 60},
            )
        remaining = MAX_FAILED_ATTEMPTS - state.failed_count
        db.commit()
        raise HTTPException(
            status_code=401,
            detail={"code": "wrong_password", "remaining_attempts": remaining},
        )

    state.failed_count = 0
    state.locked_until = None
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = new_token()
    expires_at = now + timedelta(days=SESSION_DAYS)
    db.add(AuthSession(token_hash=hash_token(token), created_at=now, expires_at=expires_at))
    db.commit()
    return {"token": token, "expires_at": expires_at.isoformat() + "Z"}


@router.get("/me")
def me(session: AuthSession = Depends(require_auth)):
    return {"ok": True, "expires_at": session.expires_at.isoformat() + "Z"}
