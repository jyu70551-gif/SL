"""근처 학교의 방학을 공식 학사일정에서 가져오기 (docs/plan.md 6-2). 모든 주소는 비밀번호 통행증이 있어야 합니다.

흐름: 점포 위치(위도·경도) → 반경 500m 학교 목록 → 점주가 반영할 학교를 고름 → 학교별 방학 기간 추정(미리보기)
      → 점주가 맞다고 확인한 것만 방학 목록에 저장(출처 official). 확인하지 않은 일정은 저장되지 않습니다.
"""
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import config, official
from app.auth import get_db, require_auth
from app.models import ScheduleEvent
from app.settings import VACATION, store_location, vacation_items

router = APIRouter(prefix="/api/settings/schools", tags=["schools"], dependencies=[Depends(require_auth)])

PLACES_TTL_SECONDS = 24 * 3600  # 전국 학교 위치는 하루에 한 번만 받습니다 (자주 바뀌지 않음)
MAX_SCHOOLS = 10  # 한 번에 미리볼 수 있는 학교 수
MAX_SAVE = 40
_places_cache: dict = {"at": 0.0, "places": []}


def _get(request: Request):
    return getattr(request.app.state, "official_get", official.fetch_json)


def _key(name: str) -> str:
    return config.read_env_key(name, config.AI_ENV_FILE)


def _unavailable(error: official.OfficialError):
    raise HTTPException(status_code=502, detail={"code": "source_unavailable", "reason": error.code})


def _places(request: Request) -> list[dict]:
    if _places_cache["places"] and time.monotonic() - _places_cache["at"] < PLACES_TTL_SECONDS:
        return _places_cache["places"]
    try:
        places = official.load_school_places(_get(request), _key("DATA_GO_KR_API_KEY"))
    except official.OfficialError as error:
        _unavailable(error)
    _places_cache.update(at=time.monotonic(), places=places)
    return places


@router.get("")
def nearby_schools(request: Request, db: Session = Depends(get_db)):
    """점포 반경 500m 안의 학교. 위치나 키가 없으면 status 로 알려 줍니다."""
    base = {"radius_m": official.RADIUS_M, "items": []}
    location = store_location(db)
    if location is None:
        return {**base, "status": "no_location"}
    if not _key("DATA_GO_KR_API_KEY"):
        return {**base, "status": "no_key"}
    return {**base, "status": "ready", "items": official.nearby(_places(request), *location)}


class PreviewBody(BaseModel):
    school_ids: list[str] = []


def _existing_vacations(db: Session) -> set[tuple[str, str, str]]:
    return {(e.name, e.start_date.isoformat(), e.end_date.isoformat()) for e in db.scalars(select(ScheduleEvent).where(ScheduleEvent.kind == VACATION))}


@router.post("/vacations")
def preview_vacations(body: PreviewBody, request: Request, db: Session = Depends(get_db)):
    """고른 학교들의 방학 기간 추정(미리보기). 아무것도 저장하지 않습니다."""
    ids = list(dict.fromkeys(body.school_ids))
    if not ids or len(ids) > MAX_SCHOOLS:
        raise HTTPException(status_code=422, detail={"code": "invalid_schools"})
    if not _key("NEIS_API_KEY"):
        return {"status": "no_key", "schools": []}
    by_id = {p["school_id"]: p for p in _places(request)}
    if any(i not in by_id for i in ids):
        raise HTTPException(status_code=404, detail={"code": "unknown_school"})
    get, neis_key = _get(request), _key("NEIS_API_KEY")
    today = date.today()
    start, end = date(today.year - 1, 1, 1), date(today.year + 1, 12, 31)
    saved = _existing_vacations(db)
    schools = []
    for school_id in ids:
        place = by_id[school_id]
        entry = {"school_id": school_id, "name": place["name"], "kind": place["kind"], "status": "ok", "periods": []}
        atpt = official.atpt_code_of(place["edu_office"])
        try:
            found = official.neis_school_code(get, neis_key, atpt, place["name"], place["address"])
            if found is None:
                entry["status"] = "no_code"  # NEIS에서 이 학교를 찾지 못함 → 점주가 직접 입력
            else:
                for period in official.vacation_periods(official.fetch_schedule(get, neis_key, found[0], found[1], start, end)):
                    name = _event_name(place["name"], period["label"])
                    entry["periods"].append({**period, "already_saved": (name, period["start_date"], period["end_date"]) in saved})
                if not entry["periods"]:
                    entry["status"] = "none_found"  # 방학으로 볼 수 있는 일정이 없음 → 점주가 직접 입력
        except official.OfficialError:
            entry["status"] = "unavailable"
        schools.append(entry)
    return {"status": "ready", "schools": schools}


def _event_name(school: str, label: str) -> str:
    return f"{school} {label}"[:60]


class SaveItem(BaseModel):
    school_id: str
    label: str = "방학"
    start_date: str
    end_date: str


class SaveBody(BaseModel):
    items: list[SaveItem] = []


@router.post("/vacations/save")
def save_vacations(body: SaveBody, request: Request, db: Session = Depends(get_db)):
    """점주가 맞다고 확인한 방학만 저장합니다. 이미 같은 이름·날짜로 저장된 것은 건너뜁니다."""
    if not body.items or len(body.items) > MAX_SAVE:
        raise HTTPException(status_code=422, detail={"code": "no_items"})
    by_id = {p["school_id"]: p for p in _places(request)}
    parsed = []
    for item in body.items:
        place = by_id.get(item.school_id)
        if place is None:
            raise HTTPException(status_code=404, detail={"code": "unknown_school"})
        try:
            start, end = date.fromisoformat(item.start_date), date.fromisoformat(item.end_date)
        except ValueError:
            raise HTTPException(status_code=422, detail={"code": "invalid_date"}) from None
        if end < start:
            raise HTTPException(status_code=422, detail={"code": "end_before_start"})
        parsed.append((_event_name(place["name"], item.label.strip()[:20] or "방학"), start, end))
    existing = _existing_vacations(db)
    added = 0
    for name, start, end in parsed:
        key = (name, start.isoformat(), end.isoformat())
        if key in existing:
            continue
        existing.add(key)
        db.add(ScheduleEvent(kind=VACATION, name=name, start_date=start, end_date=end, source="official"))
        added += 1
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail={"code": "save_failed"}) from None
    return {"saved": added, "items": vacation_items(db)}
