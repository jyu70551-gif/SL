"""확인이 필요한 대분류 (spec 3번). 모든 주소는 비밀번호 통행증이 있어야 합니다.

어떻게 고르나 (PRD 미정 7번. 점주와 정한 것 + 개발하면서 정한 값. 아래 숫자만 바꾸면 전체에 반영됩니다)
- 판단 기준은 대분류의 **하루 매출금액**입니다.
- 대분류마다 **자기 자신의 평소**와 따로 비교합니다. 평소 = 그날보다 앞선 **같은 요일, 같은 시각까지**의
  기록 **전부**(쌓일수록 모두 반영). 3번 이상 쌓여야 판단하고, 모자라면 "데이터가 더 필요해요"입니다.
- 파일에 줄이 없는 대분류는 그날 0원으로 봅니다.
- 점수 = (그날 금액 − 평소 중간값) ÷ 흩어진 정도. 점수 3 이상이고 차이가 5,000원 이상이면 이상한 날입니다.
  (중간값과 흩어진 정도는 한 번 튄 값에 덜 흔들리게 하려고 평균 대신 씁니다)
- **거의 늘 0인 대분류**(평소의 절반 이상이 0원)는 따로 봅니다. 안 팔린 날은 이상으로 보지 않고,
  팔린 날만 팔렸을 때의 금액끼리 비교합니다.
- 홈 목록에는 가장 최근 올린 날짜로부터 7일 안의 이상한 날 중, 아직 "확인함·정상"을 누르지 않은 것만 올립니다.
"""
from datetime import date, timedelta
from statistics import median

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import auth
from app.auth import get_db, require_auth
from app.models import DailySale, ReviewedAnomaly, SalesUpload

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"], dependencies=[Depends(require_auth)])

MIN_SAME_WEEKDAY_DAYS = 3  # 홈의 같은 요일 비교와 같은 기준
RECENT_DAYS = 7  # 홈 목록에 올리는 기간
SCORE_THRESHOLD = 3.0
MIN_AMOUNT_GAP = 5000  # 원. 이보다 작은 차이는 이상으로 보지 않습니다.
SCALE_FLOOR_RATIO = 0.15  # 흩어진 정도의 하한: 평소 중간값의 15%
SCALE_FLOOR_AMOUNT = 1000  # 원
SPARSE_ZERO_SHARE = 0.5  # 평소의 이 비율 이상이 0원이면 "거의 늘 0인 대분류"
SPARSE_NEW_MIN_AMOUNT = 20000  # 한 번도 안 팔리던 대분류가 팔릴 때 이상으로 보는 최소 금액
SERIES_DAYS = 60  # 그래프에 보여주는 최대 일수
WEEKDAYS = "월화수목금토일"


def _amounts_by_date(db: Session) -> dict[date, dict[str, int]]:
    rows = db.execute(
        select(DailySale.sales_date, DailySale.category, func.sum(DailySale.amount)).group_by(
            DailySale.sales_date, DailySale.category
        )
    ).all()
    result: dict[date, dict[str, int]] = {}
    for sales_date, category, amount in rows:
        result.setdefault(sales_date, {})[category] = int(amount)
    return result


def _scale(values: list[float], center: float) -> float:
    mad = median(abs(v - center) for v in values)
    return max(1.4826 * mad, SCALE_FLOOR_RATIO * center, SCALE_FLOOR_AMOUNT)


def baseline_of(history: list[int]) -> tuple[int, bool]:
    """비교 기준 금액과 '거의 늘 0인 대분류' 여부. 판정과 화면 표시가 같은 기준을 쓰도록 한 곳에서 계산합니다."""
    zeros = sum(1 for v in history if v == 0)
    if zeros / len(history) >= SPARSE_ZERO_SHARE:
        sold = [v for v in history if v > 0]
        return (round(median(sold)) if sold else 0), True
    return round(median(history)), False


def judge(amount: int, history: list[int]) -> dict | None:
    """그날 금액이 평소(history)와 많이 다른지. 이상하면 설명 값을, 아니면 None을 돌려줍니다."""
    zeros = sum(1 for v in history if v == 0)
    if zeros / len(history) >= SPARSE_ZERO_SHARE:
        sold = [v for v in history if v > 0]
        if amount == 0:
            return None  # 안 팔린 날은 평소 모습입니다.
        if not sold:
            if amount < SPARSE_NEW_MIN_AMOUNT:
                return None
            return {"direction": "high", "baseline": 0, "score": None}
        center = float(median(sold))
        base = center
        values = [float(v) for v in sold]
    else:
        center = float(median(history))
        base = center
        values = [float(v) for v in history]

    score = (amount - center) / _scale(values, center)
    if abs(score) < SCORE_THRESHOLD or abs(amount - center) < MIN_AMOUNT_GAP:
        return None
    return {"direction": "high" if score > 0 else "low", "baseline": round(base), "score": round(score, 1)}


def _change_pct(amount: int, baseline: int) -> float | None:
    if baseline == 0:
        return None
    return round((amount - baseline) / baseline * 100, 1)


def _analyze(db: Session) -> dict:
    """모든 날짜 × 대분류를 판단합니다. 올린 데이터가 작아서 매번 새로 계산해도 충분히 빠릅니다."""
    uploads = list(db.scalars(select(SalesUpload).order_by(SalesUpload.sales_date)))
    amounts = _amounts_by_date(db)
    categories = sorted({c for per_day in amounts.values() for c in per_day})
    reviewed = {(r.category, r.sales_date): r for r in db.scalars(select(ReviewedAnomaly))}

    # judged[(대분류, 날짜)] = {"amount", "baseline", "change_pct", "direction", "score", "weeks_used"}
    judged: dict[tuple[str, date], dict] = {}
    weeks_used: dict[date, int] = {}
    for upload in uploads:
        earlier = [
            u
            for u in uploads
            if u.sales_date < upload.sales_date
            and u.sales_date.weekday() == upload.sales_date.weekday()
            and u.cutoff_hour == upload.cutoff_hour
        ]
        weeks_used[upload.sales_date] = len(earlier)
        for category in categories:
            amount = amounts.get(upload.sales_date, {}).get(category, 0)
            entry = {
                "amount": amount,
                "weeks_used": len(earlier),
                "baseline_dates": [u.sales_date.isoformat() for u in earlier],
                "anomaly": None,
            }
            if len(earlier) >= MIN_SAME_WEEKDAY_DAYS:
                history = [amounts.get(u.sales_date, {}).get(category, 0) for u in earlier]
                verdict = judge(amount, history)
                entry["typical"], entry["sparse"] = baseline_of(history)
                if verdict:
                    verdict["change_pct"] = _change_pct(amount, verdict["baseline"])
                    entry["anomaly"] = verdict
            judged[(category, upload.sales_date)] = entry

    return {
        "uploads": uploads,
        "categories": categories,
        "judged": judged,
        "reviewed": reviewed,
        "weeks_used": weeks_used,
    }


def _day(d: date) -> dict:
    return {"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()]}


def build_anomaly_list(db: Session) -> dict:
    data = _analyze(db)
    uploads = data["uploads"]
    if not uploads:
        return {"has_data": False}

    latest = uploads[-1]
    window_start = latest.sales_date - timedelta(days=RECENT_DAYS - 1)
    in_window = [u for u in uploads if u.sales_date >= window_start]
    used = data["weeks_used"][latest.sales_date]

    result: dict = {
        "has_data": True,
        "date": latest.sales_date.isoformat(),
        "cutoff_hour": latest.cutoff_hour,
        "status": "ready" if used >= MIN_SAME_WEEKDAY_DAYS else "not_enough",
        "weeks_used": used,
        "min_days": MIN_SAME_WEEKDAY_DAYS,
        "needed_more": max(0, MIN_SAME_WEEKDAY_DAYS - used),
        "items": [],
    }
    # 최근 7일 중 하루라도 판단할 수 있으면 목록을 보여줍니다.
    judgeable = any(data["weeks_used"][u.sales_date] >= MIN_SAME_WEEKDAY_DAYS for u in in_window)
    if not judgeable:
        return result
    result["status"] = "ready"

    for category in data["categories"]:
        flagged = []
        for upload in in_window:
            entry = data["judged"][(category, upload.sales_date)]
            anomaly = entry["anomaly"]
            if anomaly is None or (category, upload.sales_date) in data["reviewed"]:
                continue
            flagged.append(
                {
                    **_day(upload.sales_date),
                    "amount": entry["amount"],
                    "baseline": anomaly["baseline"],
                    "change_pct": anomaly["change_pct"],
                    "direction": anomaly["direction"],
                    "cutoff_hour": upload.cutoff_hour,
                    "weeks_used": entry["weeks_used"],
                }
            )
        if flagged:
            flagged.sort(key=lambda f: f["date"], reverse=True)
            result["items"].append({"category": category, "flagged": flagged})

    # 가장 최근에 이상했던 대분류가 위로 오게 합니다.
    result["items"].sort(key=lambda item: item["flagged"][0]["date"], reverse=True)
    return result


def build_series(db: Session, category: str) -> dict:
    data = _analyze(db)
    if category not in data["categories"]:
        raise HTTPException(status_code=404, detail={"code": "unknown_category"})
    points = []
    for upload in data["uploads"][-SERIES_DAYS:]:
        entry = data["judged"][(category, upload.sales_date)]
        anomaly = entry["anomaly"]
        points.append(
            {
                **_day(upload.sales_date),
                "amount": entry["amount"],
                "cutoff_hour": upload.cutoff_hour,
                "typical": entry.get("typical"),
                "sparse": entry.get("sparse", False),
                "weeks_used": entry["weeks_used"],
                "baseline_dates": entry["baseline_dates"],
                "record": _record_of(data["reviewed"].get((category, upload.sales_date))),
                "anomaly": (
                    {
                        "direction": anomaly["direction"],
                        "baseline": anomaly["baseline"],
                        "change_pct": anomaly["change_pct"],
                        "reviewed": (category, upload.sales_date) in data["reviewed"],
                    }
                    if anomaly
                    else None
                ),
            }
        )
    judgeable = sum(1 for p in points if p["typical"] is not None)
    return {
        "category": category,
        "status": "ready" if judgeable else "not_enough",
        "min_days": MIN_SAME_WEEKDAY_DAYS,
        "points": points,
    }


# 당시 특이사항 선택지. 점주가 직접 고른 기록이며 통계로 입증된 원인이 아닙니다.
REASONS = {
    "promo": "행사·진열 변경",
    "bulk": "단체 구매",
    "stock": "입고·품절 관련 사항",
    "data_check": "데이터 확인 필요",
    "other": "기타",
    "unknown": "모르겠어요",
}
MAX_MEMO_LENGTH = 300


def _record_of(record: ReviewedAnomaly | None) -> dict | None:
    if record is None:
        return None
    keys = [k for k in record.reasons.split(",") if k in REASONS]
    return {"reasons": keys, "reason_labels": [REASONS[k] for k in keys], "memo": record.memo}


class ReviewBody(BaseModel):
    category: str
    dates: list[date]
    reasons: list[str] = []
    memo: str = ""


class UnreviewBody(BaseModel):
    category: str
    date: date


@router.get("")
def anomaly_list(db: Session = Depends(get_db)):
    return build_anomaly_list(db)


@router.get("/series")
def anomaly_series(category: str, db: Session = Depends(get_db)):
    return build_series(db, category)


@router.get("/reviewed")
def reviewed_list(db: Session = Depends(get_db)):
    data = _analyze(db)
    items = []
    for (category, sales_date), record in data["reviewed"].items():
        entry = data["judged"].get((category, sales_date))
        if entry is None:
            continue
        anomaly = entry["anomaly"] or {}
        items.append(
            {
                "category": category,
                **_day(sales_date),
                "amount": entry["amount"],
                "baseline": anomaly.get("baseline"),
                "change_pct": anomaly.get("change_pct"),
                "direction": anomaly.get("direction"),
                "reviewed_at": record.reviewed_at.isoformat() + "Z",
                "weeks_used": entry["weeks_used"],
                **_record_of(record),
            }
        )
    items.sort(key=lambda i: (i["date"], i["category"]), reverse=True)
    return {"items": items}


@router.post("/review")
def review(body: ReviewBody, db: Session = Depends(get_db)):
    """"확인함·정상". 한 번에 여러 날짜를 처리해도 전부 저장되거나 전혀 저장되지 않습니다."""
    if not body.dates:
        raise HTTPException(status_code=422, detail={"code": "no_dates"})
    known = set(db.scalars(select(SalesUpload.sales_date).where(SalesUpload.sales_date.in_(body.dates))))
    if known != set(body.dates):
        raise HTTPException(status_code=404, detail={"code": "unknown_date"})
    unknown = [r for r in body.reasons if r not in REASONS]
    memo = body.memo.strip()
    if unknown or len(memo) > MAX_MEMO_LENGTH:
        raise HTTPException(status_code=422, detail={"code": "invalid_record"})
    reasons = ",".join(dict.fromkeys(body.reasons))  # 중복 제거, 순서 유지
    try:
        existing = {
            r.sales_date: r
            for r in db.scalars(
                select(ReviewedAnomaly).where(
                    ReviewedAnomaly.category == body.category, ReviewedAnomaly.sales_date.in_(body.dates)
                )
            )
        }
        now = auth.utcnow()
        for d in set(body.dates):
            row = existing.get(d)
            if row is None:
                db.add(ReviewedAnomaly(category=body.category, sales_date=d, reviewed_at=now, reasons=reasons, memo=memo))
            elif body.reasons or memo:
                # 이미 기록된 날짜를 다시 저장하면 내용만 고칩니다. (선택·메모 없이 다시 눌러도 기존 내용은 지우지 않습니다)
                row.reasons, row.memo, row.reviewed_at = reasons, memo, now
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail={"code": "save_failed"})
    return {"reviewed": len(set(body.dates))}


@router.post("/unreview")
def unreview(body: UnreviewBody, db: Session = Depends(get_db)):
    try:
        db.execute(
            delete(ReviewedAnomaly).where(
                ReviewedAnomaly.category == body.category, ReviewedAnomaly.sales_date == body.date
            )
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail={"code": "save_failed"})
    return {"ok": True}
