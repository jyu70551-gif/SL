"""총매출 분석 (홈 '매출 요약'의 상세 화면). 모든 주소는 비밀번호 통행증이 있어야 합니다.

점주와 정한 방식: 쌓인 기록으로 평소의 분포를 그리고, 오늘 값이 그 분포의 어디에 놓이는지로 판단합니다.
(아래 숫자만 바꾸면 전체에 반영됩니다)
- 자료: 오늘보다 앞선 **모든 요일** 중 **같은 시각까지** 집계한 총매출 **전부**. 3번 이상 쌓여야 판단합니다.
  (점주 요청으로 같은 요일로 좁히지 않습니다. 요일에 따른 차이도 평소의 흔들림에 포함됩니다)
  (마감 시각이 다른 날은 누적 금액이 달라 비교할 수 없으므로 뺍니다)
- 분포: 매출은 '몇 %씩' 흔들리는 성질이 있어 **비율 기준(로그)**으로 정규분포를 맞춥니다. (평소 범위가 0원 아래로 내려가지 않음)
  0원 이하인 날이 하나라도 있으면 금액 그대로 계산합니다.
- 판정: 오늘 값이 분포의 95% 예측 범위를 벗어나는지 Student t 예측구간 검정(양쪽, 유의수준 5%)으로 봅니다.
  t = (오늘 − 평균) ÷ (표준편차 × √(1 + 1/n)),  자유도 = n − 1
  자료가 적으면 t 분포가 알아서 범위를 넓혀 보수적으로 판정하고, 쌓일수록 범위가 좁아집니다.
- 함께 보여주는 것: 평소 중심값, 95% 예상 범위, 분포 안의 위치(상위·하위 %), 기록 중 오늘보다 낮았던 날 수.
- 홈 매출 요약의 '최근 4번 평균'과는 기준이 다릅니다. (홈은 최근 4번 평균, 여기는 쌓인 전체의 분포)
"""
import math
from statistics import mean, stdev

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_db, require_auth
from app.models import DailySale, SalesUpload
from app.stats import t_cdf, t_ppf

router = APIRouter(prefix="/api/sales", tags=["sales"], dependencies=[Depends(require_auth)])

MIN_DAYS = 3  # 판단에 필요한 최소 기록 수 (홈의 같은 요일 비교와 같은 기준)
ALPHA = 0.05  # 유의수준 (95% 범위)
FEW_DATA_UNDER = 5  # 이보다 적으면 "자료가 적어 참고용"
SERIES_DAYS = 120  # 그래프에 보여주는 최대 일수
WEEKDAYS = "월화수목금토일"


def evaluate(history: list[int], today: int) -> dict:
    """쌓인 기록(history)의 분포에서 오늘 값(today)이 어디에 놓이는지 계산합니다."""
    n = len(history)
    base = {"n": n, "min_days": MIN_DAYS, "alpha": ALPHA}
    if n < MIN_DAYS:
        return {**base, "status": "not_enough", "needed_more": MIN_DAYS - n}

    use_log = today > 0 and all(v > 0 for v in history)
    values = [math.log(v) for v in history] if use_log else [float(v) for v in history]
    y = math.log(today) if use_log else float(today)

    mu = mean(values)
    sd = stdev(values)
    below = sum(1 for v in history if v < today)
    ties = sum(1 for v in history if v == today)
    common = {
        **base,
        "scale": "log" if use_log else "raw",
        "rank_below": below,
        "rank_ties": ties,
        "few_data": n < FEW_DATA_UNDER,
    }
    if sd == 0:
        return {**common, "status": "no_variation"}

    df = n - 1
    spread = sd * math.sqrt(1 + 1 / n)  # 새 값 하나가 흩어지는 정도
    t = (y - mu) / spread
    p_value = 2 * (1 - t_cdf(abs(t), df))
    crit = t_ppf(1 - ALPHA / 2, df)
    back = math.exp if use_log else float
    center = back(mu)
    low = back(mu - crit * spread)
    high = back(mu + crit * spread)
    if not use_log:
        low = max(0.0, low)
    verdict = "none" if p_value >= ALPHA else ("increase" if t > 0 else "decrease")
    cdf = t_cdf(t, df)
    return {
        **common,
        "status": "ready",
        "center": round(center),
        "low": round(low),
        "high": round(high),
        "t": round(t, 2),
        "df": df,
        "p_value": round(p_value, 3),
        "verdict": verdict,
        # 분포 안의 위치: 높은 쪽이면 상위 x%, 낮은 쪽이면 하위 x%
        "side": "high" if t >= 0 else "low",
        "tail_pct": round(min(cdf, 1 - cdf) * 100, 1),
    }


def build_sales_detail(db: Session) -> dict:
    latest = db.scalar(select(SalesUpload).order_by(SalesUpload.sales_date.desc()).limit(1))
    if latest is None:
        return {"has_data": False}

    uploads = list(db.scalars(select(SalesUpload).order_by(SalesUpload.sales_date)))
    amount_by_date = {
        d: int(total or 0)
        for d, total in db.execute(select(DailySale.sales_date, func.sum(DailySale.amount)).group_by(DailySale.sales_date))
    }
    qty_by_date = {
        d: int(total or 0)
        for d, total in db.execute(select(DailySale.sales_date, func.sum(DailySale.quantity)).group_by(DailySale.sales_date))
    }

    today, hour = latest.sales_date, latest.cutoff_hour
    weekday = today.weekday()
    same_hour = [u for u in uploads if u.cutoff_hour == hour]
    excluded = len(uploads) - len(same_hour)
    history_uploads = [u for u in same_hour if u.sales_date < today]  # 요일은 가리지 않습니다
    history = [amount_by_date.get(u.sales_date, 0) for u in history_uploads]
    today_total = amount_by_date.get(today, 0)

    points = [
        {
            "date": u.sales_date.isoformat(),
            "weekday": WEEKDAYS[u.sales_date.weekday()],
            "amount": amount_by_date.get(u.sales_date, 0),
            "used": u in history_uploads,  # 평소 분포에 쓴 날
            "is_today": u.sales_date == today,
        }
        for u in same_hour[-SERIES_DAYS:]
    ]
    return {
        "has_data": True,
        "date": today.isoformat(),
        "weekday": WEEKDAYS[weekday],
        "cutoff_hour": hour,
        "today": {"total_amount": today_total, "total_quantity": qty_by_date.get(today, 0)},
        "points": points,
        "excluded_other_hour": excluded,
        "used_dates": [u.sales_date.isoformat() for u in history_uploads],
        "test": evaluate(history, today_total),
    }


@router.get("/detail")
def sales_detail(db: Session = Depends(get_db)):
    return build_sales_detail(db)
