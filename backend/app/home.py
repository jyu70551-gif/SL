"""홈 카드에 보여줄 숫자 (spec 4번, 5번, 8-2). 통행증이 있어야 합니다.

기준 (spec에 적히지 않아 개발하면서 정한 값입니다. 아래 숫자만 바꾸면 전체에 반영됩니다)
- 오늘 = 올려 둔 파일 중 가장 최근 날짜
- "같은 요일 평소" = 오늘보다 앞선 같은 요일 중, **같은 시각까지의 매출**끼리 최근 4번의 평균
  (마감 시각이 다르면 누적 금액이 달라서 비교가 틀어지므로 시각이 같은 날만 씁니다)
- 같은 요일 데이터가 3번 이상 쌓여야 비교를 보여줍니다. 모자라면 "데이터가 더 필요해요"
"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_db, require_auth
from app.models import DailySale, SalesUpload

router = APIRouter(prefix="/api/home", tags=["home"], dependencies=[Depends(require_auth)])

MIN_SAME_WEEKDAY_DAYS = 3
MAX_SAME_WEEKDAY_DAYS = 4
INSTANT_FOOD_CATEGORIES = ["간편식사", "즉석조리"]
WEEKDAYS = "월화수목금토일"


def _change_pct(today: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return round((today - baseline) / baseline * 100, 1)


def _totals_by_date_and_category(db: Session, dates: list[date]):
    """{날짜: {대분류: (수량 합, 판매액 합)}}"""
    result: dict[date, dict[str, tuple[int, int]]] = {d: {} for d in dates}
    if not dates:
        return result
    rows = db.execute(
        select(
            DailySale.sales_date,
            DailySale.category,
            func.sum(DailySale.quantity),
            func.sum(DailySale.amount),
        )
        .where(DailySale.sales_date.in_(dates))
        .group_by(DailySale.sales_date, DailySale.category)
    ).all()
    for sales_date, category, quantity, amount in rows:
        result[sales_date][category] = (int(quantity), int(amount))
    return result


def _sum_all(by_category: dict[str, tuple[int, int]]) -> tuple[int, int]:
    return (
        sum(q for q, _ in by_category.values()),
        sum(a for _, a in by_category.values()),
    )


def build_home_summary(db: Session) -> dict:
    latest = db.scalar(select(SalesUpload).order_by(SalesUpload.sales_date.desc()).limit(1))
    if latest is None:
        return {"has_data": False}

    today = latest.sales_date
    hour = latest.cutoff_hour
    weekday = today.weekday()

    earlier_same_weekday = [
        u
        for u in db.scalars(
            select(SalesUpload).where(SalesUpload.sales_date < today).order_by(SalesUpload.sales_date.desc())
        )
        if u.sales_date.weekday() == weekday
    ]
    same_hour = [u for u in earlier_same_weekday if u.cutoff_hour == hour]
    used = same_hour[:MAX_SAME_WEEKDAY_DAYS]
    used_dates = [u.sales_date for u in used]

    totals = _totals_by_date_and_category(db, [today, *used_dates])
    today_cats = totals[today]
    today_qty, today_amount = _sum_all(today_cats)

    ready = len(used) >= MIN_SAME_WEEKDAY_DAYS
    needed_more = max(0, MIN_SAME_WEEKDAY_DAYS - len(used))
    common = {
        "weeks_used": len(used),
        "used_dates": [d.isoformat() for d in used_dates],
        "needed_more": needed_more,
        "min_days": MIN_SAME_WEEKDAY_DAYS,
        "excluded_other_hour": len(earlier_same_weekday) - len(same_hour),
    }

    comparison: dict = {"status": "ready" if ready else "not_enough", **common}
    if ready:
        history = [_sum_all(totals[d]) for d in used_dates]
        base_qty = sum(q for q, _ in history) / len(history)
        base_amount = sum(a for _, a in history) / len(history)
        comparison.update(
            baseline_quantity=round(base_qty),
            baseline_amount=round(base_amount),
            quantity_change_pct=_change_pct(today_qty, base_qty),
            amount_change_pct=_change_pct(today_amount, base_amount),
        )

    instant_items = []
    for category in INSTANT_FOOD_CATEGORIES:
        qty = today_cats.get(category, (0, 0))[0]
        item: dict = {
            "category": category,
            "today_quantity": qty,
            "status": "ready" if ready else "not_enough",
            **common,
        }
        if ready:
            values = [totals[d].get(category, (0, 0))[0] for d in used_dates]
            low, high = min(values), max(values)
            item.update(
                baseline_quantity=round(sum(values) / len(values), 1),
                range_min=low,
                range_max=high,
                verdict="high" if qty > high else "low" if qty < low else "normal",
            )
        instant_items.append(item)

    return {
        "has_data": True,
        "date": today.isoformat(),
        "weekday": WEEKDAYS[weekday],
        "cutoff_hour": hour,
        "today": {"total_amount": today_amount, "total_quantity": today_qty},
        "comparison": comparison,
        "instant_food": instant_items,
    }


@router.get("/summary")
def home_summary(db: Session = Depends(get_db)):
    return build_home_summary(db)
