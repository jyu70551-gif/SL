"""공휴일 가져오기 (docs/plan.md 6-2). 한국천문연구원 특일 정보(공공데이터포털)에서 올해와 내년 공휴일을 받아
점주가 확인한 뒤 저장합니다. 대체공휴일·임시공휴일도 공식 자료에 올라오면 함께 들어옵니다. AI는 쓰지 않습니다.
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import official
from app.auth import get_db, require_auth
from app.models import ScheduleEvent
from app.schools import _get, _key, _unavailable
from app.settings import _save

router = APIRouter(prefix="/api/settings/holidays", tags=["holidays"], dependencies=[Depends(require_auth)])

HOLIDAY = "holiday"


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
