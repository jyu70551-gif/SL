"""공휴일 가져오기 (docs/plan.md 6-2). 한국천문연구원 특일 정보(공공데이터포털)에서 올해와 내년 공휴일을 받아
저장합니다. 대체공휴일·임시공휴일도 공식 자료에 올라오면 함께 들어옵니다. AI는 쓰지 않습니다.
공휴일은 점주가 따로 확인할 것이 없어서, 홈을 열 때 알아서 가져옵니다(auto_sync). 설정의 가져오기는 자동이 안 될 때의 보조 수단입니다.
"""
import logging
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import official
from app.auth import get_db, require_auth
from app.models import ScheduleEvent
from app.schools import _get, _key, _unavailable
from app.settings import _save

router = APIRouter(prefix="/api/settings/holidays", tags=["holidays"], dependencies=[Depends(require_auth)])

HOLIDAY = "holiday"
logger = logging.getLogger("sl")

# 올해·내년이 다 있으면 하루에 한 번만 새로 확인하고(임시공휴일 등이 뒤늦게 올라올 수 있어서), 비어 있으면 6시간마다 다시 시도합니다.
AUTO_REFRESH_SECONDS = 24 * 3600
AUTO_RETRY_SECONDS = 6 * 3600


def _saved(db: Session) -> set[tuple[date, str]]:
    return {(e.start_date, e.name) for e in db.scalars(select(ScheduleEvent).where(ScheduleEvent.kind == HOLIDAY))}


def _counts(db: Session) -> dict:
    year = date.today().year
    days = [d for d, _ in _saved(db)]
    return {"this_year": year, "this_year_count": sum(d.year == year for d in days), "next_year_count": sum(d.year == year + 1 for d in days)}


def _official_holidays(request: Request) -> list[dict]:
    key, get, year = _key("HOLIDAY_API_KEY"), _get(request), date.today().year
    try:
        return official.fetch_holidays(get, key, year) + official.fetch_holidays(get, key, year + 1)
    except official.OfficialError as error:
        _unavailable(error)


def auto_sync(request: Request, db: Session) -> None:
    """올해·내년 공휴일을 조용히 가져와 저장합니다. 키가 없거나 연결이 안 돼도 화면을 막지 않고 그냥 넘어갑니다."""
    state = request.app.state
    counts = _counts(db)
    complete = counts["this_year_count"] > 0 and counts["next_year_count"] > 0
    wait = AUTO_REFRESH_SECONDS if complete else AUTO_RETRY_SECONDS
    last = getattr(state, "holiday_sync_at", None)
    if last is not None and time.monotonic() - last < wait:
        return
    if not _key("HOLIDAY_API_KEY"):
        return
    state.holiday_sync_at = time.monotonic()
    try:
        found = _official_holidays(request)
    except Exception:  # 공식 서비스 오류든 예상 밖 오류든 홈 화면은 계속 보여 줍니다
        logger.warning("공휴일을 자동으로 가져오지 못했어요.")
        return
    saved = _saved(db)
    for h in found:
        if (h["date"], h["name"]) not in saved:
            db.add(ScheduleEvent(kind=HOLIDAY, name=h["name"], start_date=h["date"], end_date=h["date"], source="official"))
    try:
        _save(db)
    except HTTPException:
        logger.warning("자동으로 가져온 공휴일을 저장하지 못했어요.")


@router.get("")
def read_holidays(db: Session = Depends(get_db)):
    return _counts(db)


@router.post("/preview")
def preview_holidays(request: Request, db: Session = Depends(get_db)):
    """올해와 내년 공휴일을 공식 자료에서 읽어 보여 줍니다. 아무것도 저장하지 않습니다."""
    if not _key("HOLIDAY_API_KEY"):
        return {"status": "no_key", "items": []}
    saved = _saved(db)
    items = [{"date": h["date"].isoformat(), "name": h["name"], "already_saved": (h["date"], h["name"]) in saved} for h in _official_holidays(request)]
    return {"status": "ready", "items": items}


@router.post("/save")
def save_holidays(request: Request, db: Session = Depends(get_db)):
    """공식 자료의 올해·내년 공휴일 중 아직 저장하지 않은 것을 저장합니다. (같은 날짜·이름은 건너뜀)"""
    if not _key("HOLIDAY_API_KEY"):
        return {"status": "no_key", "saved": 0, **_counts(db)}
    saved, added = _saved(db), 0
    for h in _official_holidays(request):
        if (h["date"], h["name"]) in saved:
            continue
        db.add(ScheduleEvent(kind=HOLIDAY, name=h["name"], start_date=h["date"], end_date=h["date"], source="official"))
        added += 1
    _save(db)
    return {"status": "ready", "saved": added, **_counts(db)}
