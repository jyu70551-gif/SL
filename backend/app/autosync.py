"""점포 위치를 바탕으로 한 공식 자료(공휴일·날씨·근처 학교 방학·장날)를 설정 화면에서 일일이 가져오지 않아도 되게 채웁니다.

- 홈을 열 때와 점포 위치를 저장할 때 fill_in() 이 조용히 돌고, 키가 없거나 연결이 안 돼도 화면은 그대로 열립니다.
- 위치가 바뀌면 reset_region() 이 옛 지역 자료(공식 방학, 장날, 다른 관측소의 날씨)를 지웁니다. 점주가 직접 입력한 방학은 지우지 않습니다.
- 학교는 반경 안의 가까운 학교 최대 10곳의 공식 방학을 모두 저장하고, 장날은 반경 안에 5일장이 딱 하나일 때만 자동으로 정합니다.
  (여러 곳이면 어느 시장이 맞는지 알 수 없어서 점주가 설정에서 고릅니다)
"""
import logging
import time
from datetime import date

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config, holidays, markets, official, schools, weather
from app.models import MarketDay, ScheduleEvent, WeatherDaily
from app.settings import VACATION, store_location

logger = logging.getLogger("sl")

RETRY_SECONDS = 6 * 3600  # 비어 있거나 실패했으면 이만큼 뒤에 다시 시도
WEATHER_SECONDS = 3600  # 새 매출 기록으로 빠진 날이 생기면 한 시간에 한 번까지 날씨를 채움
REFRESH_SECONDS = 7 * 24 * 3600  # 이미 채워진 방학은 일주일에 한 번만 새 일정을 확인


def _due(state, name: str, wait: float) -> bool:
    """마지막 시도 후 wait 초가 지났으면 True (지났으면 지금 시각을 기록)"""
    last = getattr(state, name, None)
    if last is not None and time.monotonic() - last < wait:
        return False
    setattr(state, name, time.monotonic())
    return True


def reset_region(db: Session, new_location: tuple[float, float] | None) -> None:
    """점포 위치가 바뀌었을 때 옛 지역 자료를 지웁니다. (호출하는 쪽이 저장합니다)"""
    db.execute(delete(ScheduleEvent).where(ScheduleEvent.kind == VACATION, ScheduleEvent.source == "official"))
    db.execute(delete(MarketDay))
    if new_location is None:
        db.execute(delete(WeatherDaily))
    else:
        station = weather.nearest_station(*new_location)[0][1]
        db.execute(delete(WeatherDaily).where(WeatherDaily.station != station))


def _fill_weather(request: Request, db: Session, location: tuple[float, float]) -> None:
    key = config.read_env_key("WEATHER_PAST_API_KEY", config.AI_ENV_FILE)
    if not key or not weather.missing_days(db, date.today()) or not _due(request.app.state, "weather_fill_at", WEATHER_SECONDS):
        return
    weather.sync_observed(db, schools._get(request), key, *location)


def _fill_vacations(request: Request, db: Session, location: tuple[float, float]) -> None:
    if not (schools._key("DATA_GO_KR_API_KEY") and schools._key("NEIS_API_KEY")):
        return
    has_official = db.scalar(select(ScheduleEvent.id).where(ScheduleEvent.kind == VACATION, ScheduleEvent.source == "official").limit(1)) is not None
    if not _due(request.app.state, "vacation_fill_at", REFRESH_SECONDS if has_official else RETRY_SECONDS):
        return
    near = official.nearby(schools._places(request), *location)[: schools.MAX_SCHOOLS]
    if not near:
        return
    preview = schools.preview_vacations(schools.PreviewBody(school_ids=[s["school_id"] for s in near]), request, db)
    items = [
        schools.SaveItem(school_id=s["school_id"], label=p["label"], start_date=p["start_date"], end_date=p["end_date"])
        for s in preview.get("schools", [])
        for p in s["periods"]
        if not p["already_saved"]
    ]
    items.sort(key=lambda i: i.start_date, reverse=True)
    if items:
        schools.save_vacations(schools.SaveBody(items=items[: schools.MAX_SAVE]), request, db)


def _fill_market(request: Request, db: Session, location: tuple[float, float]) -> None:
    if not markets._key("MARKET_API_KEY") or db.scalar(select(MarketDay.day).limit(1)) is not None:
        return
    if not _due(request.app.state, "market_fill_at", RETRY_SECONDS):
        return
    periodic = [m for m in official.nearby_markets(markets._places(request), *location) if m["kind"] == "periodic"]
    if len(periodic) == 1:
        markets.save_market_days(markets.SaveBody(market_ids=[periodic[0]["market_id"]]), request, db)


def fill_in(request: Request, db: Session) -> None:
    """공휴일·날씨·학교 방학·장날을 가능한 만큼 알아서 채웁니다. 하나가 실패해도 나머지는 계속하고 화면은 막지 않습니다."""
    steps = [lambda: holidays.auto_sync(request, db)]
    location = store_location(db)
    if location is not None:
        steps += [lambda: _fill_weather(request, db, location), lambda: _fill_vacations(request, db, location), lambda: _fill_market(request, db, location)]
    for step in steps:
        try:
            step()
        except Exception:  # 공식 서비스 오류든 예상 밖 오류든, 자동 채우기는 조용히 넘어갑니다
            db.rollback()
            logger.warning("자동으로 채우지 못한 자료가 있어요.")


def forget_attempts(request: Request) -> None:
    """위치가 바뀌면 시도 기록을 지워, 새 위치의 자료를 바로 채울 수 있게 합니다."""
    for name in ("weather_fill_at", "vacation_fill_at", "market_fill_at"):
        if hasattr(request.app.state, name):
            delattr(request.app.state, name)
