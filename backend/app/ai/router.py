"""AI 관련 주소. 모두 비밀번호 통행증이 있어야 합니다. (AI 제안은 app/suggestions.py)"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai import similar
from app.auth import get_db, require_auth

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(require_auth)])


@router.get("/status")
def ai_status(request: Request):
    return request.app.state.ai.status()


@router.get("/similar")
def similar_records(category: str, date: str, db: Session = Depends(get_db)):
    """이전 운영 경험(AI를 쓰지 않고 SQL과 고정 문구로 만듭니다)"""
    return similar.find_similar(db, category, date)
