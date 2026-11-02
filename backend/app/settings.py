"""점주가 바꾸는 설정 (spec 7장). 모든 주소는 비밀번호 통행증이 있어야 합니다.

- 알림 민감도(낮음·보통·높음)
- 점포 위치(시·군·구, 동)와 장날 (매달 정한 날짜들)
- 방학 기간 (여러 개, 겹쳐도 저장. 계산할 때는 겹치는 기간을 하나로 합침)
- 비밀번호 바꾸기
위치와 장날은 점주가 직접 입력합니다. AI가 추측하지 않습니다.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_db, require_auth
from app.config import MIN_PASSWORD_LENGTH
from app.detection import DEFAULT_LEVEL, LEVELS
from app.models import AppSetting, AuthSession, AuthState, MarketDay, ScheduleEvent
from app.security import hash_password, verify_password

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])

SENSITIVITY_KEY = "sensitivity"
STORE_CITY_KEY = "store_city"
STORE_DONG_KEY = "store_dong"
SETUP_DISMISSED_KEY = "setup_dismissed"
STORE_LAT_KEY = "store_lat"
STORE_LON_KEY = "store_lon"
KOREA_LAT = (33.0, 39.0)  # 우리나라 안의 좌표만 받습니다 (잘못 붙여 넣은 값 방지)
KOREA_LON = (124.0, 132.0)
MAX_PLACE_LENGTH = 40
VACATION = "vacation"
LEVEL_TEXT = {
    "low": "알림이 적게, 분명한 변화 위주로 알려요.",
    "normal": "처음 권하는 단계예요.",
    "high": "작은 변화도 일찍 알려요. 알림이 더 많아져요.",
}


def _fail(status: int, code: str):
    raise HTTPException(status_code=status, detail={"code": code})


def _save(db: Session):
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        _fail(500, "save_failed")


def _get_value(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row is not None else ""


def _set_value(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value


# ---------------------------------------------------------------- 알림 민감도
def get_sensitivity(db: Session) -> str:
    """저장된 값이 없거나 알 수 없는 값이면 기본(보통)입니다."""
    value = _get_value(db, SENSITIVITY_KEY)
    return value if value in LEVELS else DEFAULT_LEVEL


class SensitivityBody(BaseModel):
    level: str


def _sensitivity_view(db: Session) -> dict:
    return {
        "level": get_sensitivity(db),
        "options": [{"level": key, "label": value["label"], "text": LEVEL_TEXT[key]} for key, value in LEVELS.items()],
    }


@router.get("/sensitivity")
def read_sensitivity(db: Session = Depends(get_db)):
    return _sensitivity_view(db)


@router.post("/sensitivity")
def change_sensitivity(body: SensitivityBody, db: Session = Depends(get_db)):
    if body.level not in LEVELS:
        _fail(422, "invalid_level")
    _set_value(db, SENSITIVITY_KEY, body.level)
    _save(db)
    return _sensitivity_view(db)


# ---------------------------------------------------------------- 점포 위치와 장날
class StoreBody(BaseModel):
    city: str = ""
    dong: str = ""
    market_days: list[int] = []
    latitude: float | None = None  # 점포 위치(위도·경도). 지도 앱에서 복사해 한 번 입력합니다
    longitude: float | None = None


def market_days_of(db: Session) -> list[int]:
    return sorted(db.scalars(select(MarketDay.day)))


def store_location(db: Session) -> tuple[float, float] | None:
    """저장된 점포 위치 (위도, 경도). 없으면 None"""
    lat, lon = _get_value(db, STORE_LAT_KEY), _get_value(db, STORE_LON_KEY)
    try:
        return float(lat), float(lon)
    except ValueError:
        return None


def _store_view(db: Session) -> dict:
    location = store_location(db)
    return {
        "city": _get_value(db, STORE_CITY_KEY),
        "dong": _get_value(db, STORE_DONG_KEY),
        "market_days": market_days_of(db),
        "latitude": location[0] if location else None,
        "longitude": location[1] if location else None,
    }


@router.get("/store")
def read_store(db: Session = Depends(get_db)):
    return _store_view(db)


@router.post("/store")
def change_store(body: StoreBody, db: Session = Depends(get_db)):
    city, dong = body.city.strip(), body.dong.strip()
    if len(city) > MAX_PLACE_LENGTH or len(dong) > MAX_PLACE_LENGTH:
        _fail(422, "place_too_long")
    if any(d < 1 or d > 31 for d in body.market_days):
        _fail(422, "invalid_market_day")
    has_lat, has_lon = body.latitude is not None, body.longitude is not None
    if has_lat != has_lon:
        _fail(422, "invalid_location")  # 위도와 경도는 함께 입력해야 합니다
    if has_lat and not (KOREA_LAT[0] <= body.latitude <= KOREA_LAT[1] and KOREA_LON[0] <= body.longitude <= KOREA_LON[1]):
        _fail(422, "invalid_location")
    _set_value(db, STORE_CITY_KEY, city)
    _set_value(db, STORE_DONG_KEY, dong)
    _set_value(db, STORE_LAT_KEY, repr(body.latitude) if has_lat else "")
    _set_value(db, STORE_LON_KEY, repr(body.longitude) if has_lon else "")
    db.execute(delete(MarketDay))
    db.add_all(MarketDay(day=d) for d in sorted(set(body.market_days)))
    _save(db)
    return _store_view(db)


# ---------------------------------------------------------------- 처음 설정 안내
def _setup_view(db: Session) -> dict:
    has_location = store_location(db) is not None
    dismissed = _get_value(db, SETUP_DISMISSED_KEY) == "1"
    # needs_setup: 처음 로그인했을 때 "처음 설정" 화면으로 보낼지. 건너뛰었으면 다시 보내지 않고, 홈에 안내(has_location=false)만 남깁니다.
    return {"has_location": has_location, "dismissed": dismissed, "needs_setup": not has_location and not dismissed}


@router.get("/setup")
def read_setup(db: Session = Depends(get_db)):
    return _setup_view(db)


@router.post("/setup/dismiss")
def dismiss_setup(db: Session = Depends(get_db)):
    """"나중에 하기"나 "완료". 서버에 저장하므로 다른 기기에서 로그인해도 처음 설정 화면이 다시 나오지 않습니다."""
    _set_value(db, SETUP_DISMISSED_KEY, "1")
    _save(db)
    return _setup_view(db)


# ---------------------------------------------------------------- 방학
class VacationBody(BaseModel):
    start_date: str = ""
    end_date: str = ""


def _parse_range(body: VacationBody) -> tuple[date, date]:
    try:
        start, end = date.fromisoformat(body.start_date), date.fromisoformat(body.end_date)
    except ValueError:
        _fail(422, "invalid_date")
    if end < start:  # 끝 날짜는 시작 날짜와 같거나 그 뒤여야 합니다
        _fail(422, "end_before_start")
    return start, end


def _vacation_view(event: ScheduleEvent) -> dict:
    return {
        "id": event.id,
        "start_date": event.start_date.isoformat(),
        "end_date": event.end_date.isoformat(),
        "name": event.name,
        "source": event.source,  # owner(직접 입력) / official(공식 학사일정에서 가져와 점주가 확인)
    }


def _vacations(db: Session) -> list[ScheduleEvent]:
    return list(db.scalars(select(ScheduleEvent).where(ScheduleEvent.kind == VACATION).order_by(ScheduleEvent.start_date, ScheduleEvent.id)))


def vacation_items(db: Session) -> list[dict]:
    return [_vacation_view(e) for e in _vacations(db)]


def merged_vacations(db: Session) -> list[tuple[date, date]]:
    """겹치는 방학 기간을 하나로 합친 목록 (예상 매출·탐지에서 쓸 때). 입력한 목록 자체는 바꾸지 않습니다."""
    merged: list[list[date]] = []
    for event in _vacations(db):
        if merged and event.start_date <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], event.end_date)
        else:
            merged.append([event.start_date, event.end_date])
    return [(start, end) for start, end in merged]


@router.get("/vacations")
def read_vacations(db: Session = Depends(get_db)):
    return {"items": [_vacation_view(e) for e in _vacations(db)]}


@router.post("/vacations")
def add_vacation(body: VacationBody, db: Session = Depends(get_db)):
    start, end = _parse_range(body)
    db.add(ScheduleEvent(kind=VACATION, name="방학", start_date=start, end_date=end, source="owner"))
    _save(db)
    return {"items": [_vacation_view(e) for e in _vacations(db)]}


def _vacation_or_404(db: Session, vacation_id: int) -> ScheduleEvent:
    event = db.get(ScheduleEvent, vacation_id)
    if event is None or event.kind != VACATION:
        _fail(404, "unknown_vacation")
    return event


@router.put("/vacations/{vacation_id}")
def change_vacation(vacation_id: int, body: VacationBody, db: Session = Depends(get_db)):
    start, end = _parse_range(body)
    event = _vacation_or_404(db, vacation_id)
    event.start_date, event.end_date = start, end
    _save(db)
    return {"items": [_vacation_view(e) for e in _vacations(db)]}


@router.delete("/vacations/{vacation_id}")
def remove_vacation(vacation_id: int, db: Session = Depends(get_db)):
    db.delete(_vacation_or_404(db, vacation_id))
    _save(db)
    return {"items": [_vacation_view(e) for e in _vacations(db)]}


# ---------------------------------------------------------------- 비밀번호 바꾸기
class PasswordBody(BaseModel):
    current: str = ""
    new: str = ""
    new_again: str = ""


@router.post("/password")
def change_password(body: PasswordBody, session: AuthSession = Depends(require_auth), db: Session = Depends(get_db)):
    state = db.get(AuthState, 1)
    if state is None:
        _fail(503, "not_configured")
    if not verify_password(body.current, state.password_hash):
        _fail(400, "wrong_password")  # 401 은 "로그인이 풀렸다"는 뜻이라 쓰지 않습니다
    if body.new != body.new_again:
        _fail(422, "mismatch")
    if len(body.new) < MIN_PASSWORD_LENGTH:
        _fail(422, "too_short")
    state.password_hash = hash_password(body.new)
    # 다른 기기에 남아 있던 로그인은 풀고, 지금 쓰는 기기는 그대로 둡니다.
    db.execute(delete(AuthSession).where(AuthSession.id != session.id))
    _save(db)
    return {"ok": True}
