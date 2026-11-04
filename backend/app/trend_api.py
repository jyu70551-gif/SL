"""'요즘 뜨는 식품' 주소 (docs/trends.md 11장). 비밀번호 통행증이 있어야 합니다.
화면은 이 두 주소만 씁니다: 오늘 결과와 버튼을 눌러도 되는지(GET), 오늘 결과를 만들기(POST)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import config, trend_apify, trend_today
from app.auth import get_db, require_auth

router = APIRouter(prefix="/api/trends", tags=["trends"], dependencies=[Depends(require_auth)])

ERRORS = {"no_token": 503, "ai_unavailable": 503, "busy": 409, "monthly_limit": 429, "run_cap_low": 409, "unauthorized": 502, "payment": 502, "forbidden": 502, "timeout": 504, "rate_limit": 502, "http": 502, "network": 502, "bad_response": 502}


@router.get("/today")
def today(request: Request, db: Session = Depends(get_db)):
    """오늘 보기: 저장된 결과와 버튼을 눌러도 되는지"""
    return trend_today.status(db, request.app.state.ai)


@router.post("/today/collect")
def collect_today(request: Request, db: Session = Depends(get_db)):
    """버튼: 오늘 결과가 없으면 한 번 수집합니다(하루 1회). 토큰이나 원문 오류는 돌려주지 않고 종류만 줍니다."""
    token = config.read_env_key("APIFY_TOKEN", config.AI_ENV_FILE)
    if not token:
        raise HTTPException(status_code=503, detail={"code": "no_token"})
    try:
        trend_today.run(db, token, request.app.state.ai)
    except trend_apify.ApifyError as error:
        raise HTTPException(status_code=ERRORS.get(error.code, 502), detail={"code": error.code, "hint": error.hint}) from None
    return trend_today.status(db, request.app.state.ai)
