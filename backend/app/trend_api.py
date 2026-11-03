"""'요즘 뜨는 식품' 주소 (docs/trends.md). 비밀번호 통행증이 있어야 합니다.
집계는 항상 코드가 계산해 돌려주고, AI 설명은 따로 요청합니다. AI 가 실패해도 집계와 근거 목록은 그대로 나갑니다."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import trend, trend_ai
from app.auth import get_db, require_auth

router = APIRouter(prefix="/api/trends", tags=["trends"], dependencies=[Depends(require_auth)])


def _unknown():
    raise HTTPException(status_code=404, detail={"code": "unknown_food"})


@router.get("")
def trends(db: Session = Depends(get_db)):
    return trend.build_summary(db)


@router.get("/foods/{food_id}/evidence")
def evidence(food_id: int, db: Session = Depends(get_db)):
    """근거 콘텐츠 목록(공식 발표 먼저). 원문 링크가 없는 콘텐츠(시연 데이터 등)는 url 이 빈 글입니다."""
    if not any(i["food_id"] == food_id for i in trend.build_summary(db)["items"]):
        _unknown()
    return {"items": trend.food_contents(db, food_id)}


@router.get("/foods/{food_id}/explanation")
def read_explanation(food_id: int, db: Session = Depends(get_db)):
    out = trend_ai.read(db, food_id)
    if out["status"] == "unknown_food":
        _unknown()
    return out


class ExplainBody(BaseModel):
    refresh: bool = False  # true 면 같은 근거여도 새로 만듭니다 (AI 사용 한 번이 더 들어갑니다)


@router.post("/foods/{food_id}/explanation")
def make_explanation(food_id: int, request: Request, body: ExplainBody | None = None, db: Session = Depends(get_db)):
    out = trend_ai.explain(db, request.app.state.ai, food_id, bool(body and body.refresh))
    if out["status"] == "unknown_food":
        _unknown()
    return out


@router.post("/favorites/{food_id}")
def save_favorite(food_id: int, db: Session = Depends(get_db)):
    if not trend.set_favorite(db, food_id, True):
        _unknown()
    return {"food_id": food_id, "favorite": True}


@router.delete("/favorites/{food_id}")
def remove_favorite(food_id: int, db: Session = Depends(get_db)):
    if not trend.set_favorite(db, food_id, False):
        _unknown()
    return {"food_id": food_id, "favorite": False}
