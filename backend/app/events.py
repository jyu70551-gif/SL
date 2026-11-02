"""앞으로 다가오는 날(시즌 이벤트와 공휴일) 목록 (AI 제안의 사실 재료).

공식 특일 정보에는 어린이날·어버이날 같은 법정 기념일은 있지만 빼빼로데이, 발렌타인데이 같은 상업 시즌은 없습니다.
그래서 이 파일에 **자체 표**를 두고, 점주가 저장한 공휴일(설정 "공휴일 가져오기")을 더해서 보여 줍니다.
AI가 날짜를 지어내지 않게 하려는 장치이므로, 새 이벤트는 여기에만 추가합니다.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.holidays import HOLIDAY
from app.models import ScheduleEvent

# (월, 일, 이름). 해마다 같은 날짜인 것만 넣습니다.
FIXED = [
    (2, 14, "발렌타인데이"),
    (3, 3, "삼겹살데이"),
    (3, 14, "화이트데이"),
    (4, 14, "블랙데이"),
    (5, 8, "어버이날"),
    (5, 15, "스승의 날"),
    (5, 21, "부부의 날"),
    (10, 31, "할로윈"),
    (11, 11, "빼빼로데이"),
    (12, 24, "크리스마스 이브"),
    (12, 25, "크리스마스"),
    (12, 31, "한 해의 마지막 날"),
]
# 해마다 날짜가 달라서 교육부 발표를 보고 해마다 갱신해야 하는 것
BY_DATE = {
    date(2025, 11, 13): "수능",
    date(2026, 11, 19): "수능",
}
WINDOW_DAYS = 14


def table_events(start: date, end: date) -> dict[date, str]:
    """start~end 사이의 자체 표 이벤트 {날짜: 이름}"""
    found: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        for month, day, name in FIXED:
            d = date(year, month, day)
            if start <= d <= end:
                found[d] = name
    for d, name in BY_DATE.items():
        if start <= d <= end:
            found[d] = name
    return found


def upcoming(db: Session, today: date, days: int = WINDOW_DAYS) -> list[dict]:
    """오늘부터 days일 안의 이벤트·공휴일. [{date, days_until, name, holiday}] 날짜순.
    같은 날에 자체 표 이벤트와 공휴일이 겹치면 한 항목으로 합칩니다. 예: 크리스마스(기독탄신일)."""
    end = today + timedelta(days=days)
    names = table_events(today, end)
    holidays = {e.start_date: e.name for e in db.scalars(select(ScheduleEvent).where(ScheduleEvent.kind == HOLIDAY))
                if today <= e.start_date <= end}
    out = []
    for d in sorted(set(names) | set(holidays)):
        if d in names and d in holidays and names[d] != holidays[d]:
            name, holiday = f"{names[d]}({holidays[d]})", True
        else:
            name, holiday = names.get(d) or holidays[d], d in holidays
        out.append({"date": d, "days_until": (d - today).days, "name": name, "holiday": holiday})
    return out


def holidays_saved(db: Session, year: int) -> bool:
    """그 해 공휴일이 저장돼 있는지 (없으면 AI가 공휴일을 모른다고 알려야 합니다)"""
    return any(e.start_date.year == year for e in db.scalars(select(ScheduleEvent).where(ScheduleEvent.kind == HOLIDAY)))
