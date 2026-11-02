"""AI 관련 주소 (SDD 7장). 모두 비밀번호 통행증이 있어야 하고, AI 실패는 HTTP 오류가 아니라 응답 안의 상태로 알립니다."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import briefing, notes, similar
from app.auth import get_db, require_auth, utcnow
from app.models import AiBriefing, AiFeedback, ReviewedAnomaly

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(require_auth)])

MAX_REF = 80


class DraftBody(BaseModel):
    text: str
    date: str | None = None
    category: str | None = None


class FeedbackBody(BaseModel):
    kind: str
    ref: str
    helpful: bool


@router.get("/status")
def ai_status(request: Request):
    return request.app.state.ai.status()


@router.get("/briefing")
def get_briefing(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    ai = request.app.state.ai
    session_factory = request.app.state.session_factory
    if briefing.schedule_needed(db, ai):
        if ai.is_ready():
            # AI 호출은 백그라운드에서. 화면은 기다리지 않고 "준비 중"을 받은 뒤 다시 조회합니다.
            background_tasks.add_task(briefing.ensure_for_latest, session_factory, ai)
        else:
            briefing.ensure_for_latest(session_factory, ai)  # AI 호출 없이 고정 문구만 만들기 때문에 바로 처리
            db.expire_all()
    return briefing.read_view(db, ai)


@router.post("/notes/draft")
def draft_note(body: DraftBody, request: Request, db: Session = Depends(get_db)):
    ai = request.app.state.ai
    text = (body.text or "").strip()
    if not text or len(text) > ai.settings().note_max_chars:
        raise HTTPException(status_code=422, detail={"code": "invalid_text", "max_chars": ai.settings().note_max_chars})
    if ai.state() == "ready" and not ai.note_rate_ok():
        raise HTTPException(status_code=429, detail={"code": "too_many"})
    return notes.make_draft(db, ai, text=text, hint_date=body.date, hint_category=body.category)


@router.get("/similar")
def similar_records(category: str, date: str, db: Session = Depends(get_db)):
    return similar.find_similar(db, category, date)


@router.post("/feedback")
def post_feedback(body: FeedbackBody, db: Session = Depends(get_db)):
    if body.kind not in ("briefing", "draft") or not body.ref or len(body.ref) > MAX_REF:
        raise HTTPException(status_code=422, detail={"code": "invalid_feedback"})
    db.add(AiFeedback(created_at=utcnow(), kind=body.kind, ref=body.ref, helpful=body.helpful))
    db.commit()
    return {"ok": True}


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """점주가 쓸모를 판단하는 데 쓰는 집계. 점검에 쓴 시간·입력 부담은 서버로 알 수 없어 인터뷰로 확인합니다."""
    helpful = db.scalar(select(func.count()).select_from(AiFeedback).where(AiFeedback.helpful.is_(True))) or 0
    not_helpful = db.scalar(select(func.count()).select_from(AiFeedback).where(AiFeedback.helpful.is_(False))) or 0
    by_source = dict(db.execute(select(ReviewedAnomaly.source, func.count()).group_by(ReviewedAnomaly.source)).all())
    ai_edited = db.scalar(select(func.count()).select_from(ReviewedAnomaly).where(ReviewedAnomaly.ai_edited.is_(True))) or 0
    by_mode = dict(db.execute(select(AiBriefing.mode, func.count()).group_by(AiBriefing.mode)).all())
    by_status = dict(db.execute(select(AiBriefing.status, func.count()).group_by(AiBriefing.status)).all())
    return {
        "feedback": {"helpful": helpful, "not_helpful": not_helpful},
        "notes": {"form": by_source.get("form", 0), "ai": by_source.get("ai", 0), "ai_edited": ai_edited},
        "briefing": {"ai": by_mode.get("ai", 0), "fixed": by_mode.get("fixed", 0), "failed": by_status.get("failed", 0)},
    }
