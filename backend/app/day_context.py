"""날짜에 붙는 달력 맥락 (docs/plan.md 6-3): 점주가 저장한 장날·공휴일·방학.

알림을 없애거나 바꾸지 않고, 그날이 장날·공휴일·방학이면 "참고" 한 줄과 AI 사실 묶음의 context 로만 붙입니다.
참고 맥락일 뿐 원인이 아닙니다. 아무것도 저장하지 않았으면 빈 목록입니다.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.holidays import HOLIDAY
from app.models import ScheduleEvent
from app.settings import market_days_of, merged_vacations


def build(db: Session):
    """날짜 하나를 받아 맥락 이름 목록(["공휴일(설날)", "방학", "장날"])을 돌려주는 함수. 저장된 값은 한 번만 읽습니다."""
    market_days = set(market_days_of(db))
    holidays = {e.start_date: e.name for e in db.scalars(select(ScheduleEvent).where(ScheduleEvent.kind == HOLIDAY))}
    vacations = merged_vacations(db)

    def labels(day: date) -> list[str]:
        out = []
        if day in holidays:
            out.append(f"공휴일({holidays[day]})")
        if any(start <= day <= end for start, end in vacations):
            out.append("방학")
        if day.day in market_days:
            out.append("장날")
        return out

    return labels


def note_text(labels: list[str]) -> str:
    """화면에 붙이는 한 줄. 원인으로 말하지 않고 참고로만 알립니다."""
    return f"참고: 이날은 {', '.join(labels)}이에요. 평소와 다를 수 있어요." if labels else ""
