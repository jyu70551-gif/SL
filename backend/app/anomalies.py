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

위의 하루 비교에 더해, 기록이 28일 이상 쌓이면 detection.py 의 방법이 **이어지는 변화**와 **0원이 많은 분류**까지 봅니다.
같은 칸에 두 방법이 모두 알리면 위의 하루 비교를 남깁니다. 점수 기준과 새 방법의 기준은 설정의 민감도(낮음·보통·높음)가 바꿉니다.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import auth, detection
from app.auth import get_db, require_auth
from app.models import DailySale, ReviewedAnomaly, SalesUpload
from app.settings import get_sensitivity

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


def judge(amount: int, history: list[int], threshold: float | None = None) -> dict | None:
    """그날 금액이 평소(history)와 많이 다른지. 이상하면 설명 값을, 아니면 None을 돌려줍니다."""
    threshold = SCORE_THRESHOLD if threshold is None else threshold
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
    if abs(score) < threshold or abs(amount - center) < MIN_AMOUNT_GAP:
        return None
    return {"direction": "high" if score > 0 else "low", "baseline": round(base), "score": round(score, 1)}


def _change_pct(amount: int, baseline: int) -> float | None:
    if baseline == 0:
        return None
    return round((amount - baseline) / baseline * 100, 1)


def _quantities_by_date(db: Session) -> dict[date, dict[str, int]]:
    rows = db.execute(
        select(DailySale.sales_date, DailySale.category, func.sum(DailySale.quantity)).group_by(
            DailySale.sales_date, DailySale.category
        )
    ).all()
    result: dict[date, dict[str, int]] = {}
    for sales_date, category, quantity in rows:
        result.setdefault(sales_date, {})[category] = int(quantity)
    return result


KIND_BASIS = {
    "daily": "요일 효과를 뺀 최근 흐름",
    "trend": "최근 며칠의 흐름(요일 효과 제외)",
    "streak": "최근 팔린 날 비율",
    "big_sale": "이 분류의 지난 판매 기록",
}


def kind_text(kind: str, direction: str) -> str | None:
    """화면에 붙이는 한 줄 설명. 하루 비교(daily)에는 붙이지 않습니다. 원인은 단정하지 않습니다."""
    if kind == "trend":
        return "며칠째 평소보다 계속 높아요" if direction == "high" else "며칠째 평소보다 계속 낮아요"
    if kind == "streak":
        return "평소엔 잘 안 팔리던 분류가 자주 팔려요" if direction == "high" else "평소 팔리던 분류가 며칠째 안 팔려요"
    if kind == "big_sale":
        return "이 분류로는 평소보다 훨씬 많이 팔렸어요"
    return None


_extended_cache: dict[tuple, list] = {}  # (DB 주소, 민감도, 자료 서명) -> 새 방법의 알림 목록 (계산이 무거워서 자료가 같으면 다시 하지 않음)


def _data_signature(db: Session, uploads: list[SalesUpload]) -> tuple:
    count, amount_sum, quantity_sum = db.execute(
        select(func.count(), func.coalesce(func.sum(DailySale.amount), 0), func.coalesce(func.sum(DailySale.quantity), 0))
    ).one()
    return (tuple((u.sales_date, u.cutoff_hour, u.uploaded_at) for u in uploads), int(count), int(amount_sum), int(quantity_sum))


def _extended_alarms(db: Session, uploads, amounts, categories, level: str) -> list[tuple[str, date, dict]]:
    key = (str(db.get_bind().url), level, _data_signature(db, uploads))
    cached = _extended_cache.get(key)
    if cached is not None:
        return cached
    quantities = _quantities_by_date(db)
    groups: dict[int, list[SalesUpload]] = defaultdict(list)
    for upload in uploads:
        groups[upload.cutoff_hour].append(upload)  # 같은 시각까지의 매출끼리만 비교
    alarms: list[tuple[str, date, dict]] = []
    for group in groups.values():
        dates = [u.sales_date for u in group]
        group_amounts = {c: [amounts.get(d, {}).get(c, 0) for d in dates] for c in categories}
        group_quantities = {c: [quantities.get(d, {}).get(c, 0) for d in dates] for c in categories}
        for category, cells in detection.detect(dates, group_amounts, group_quantities, level).items():
            alarms.extend((category, dates[i], alarm) for i, alarm in cells.items())
    if len(_extended_cache) >= 8:
        _extended_cache.clear()
    _extended_cache[key] = alarms
    return alarms


LEGACY = "legacy"  # 예전 방식 그대로(하루 비교만, 점수 기준은 SCORE_THRESHOLD). 시연 데이터 평가 도구가 씁니다.


def _analyze(db: Session, level: str | None = None) -> dict:
    """모든 날짜 × 대분류를 판단합니다. level 이 없으면 설정의 민감도를 씁니다. 올린 데이터가 작아서 매번 계산해도 충분히 빠릅니다."""
    level = get_sensitivity(db) if level is None else level
    threshold = None if level == LEGACY else detection.LEVELS[level]["old"]
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
                verdict = judge(amount, history, threshold)
                entry["typical"], entry["sparse"] = baseline_of(history)
                if verdict:
                    verdict["change_pct"] = _change_pct(amount, verdict["baseline"])
                    verdict["kind"] = "daily"
                    entry["anomaly"] = verdict
            judged[(category, upload.sales_date)] = entry

    if level != LEGACY:
        for category, sales_date, alarm in _extended_alarms(db, uploads, amounts, categories, level):
            entry = judged[(category, sales_date)]
            if entry["anomaly"] is None:  # 하루 비교가 이미 알렸다면 그대로 둡니다
                entry["anomaly"] = {
                    "direction": alarm["direction"],
                    "baseline": alarm["expected"],
                    "score": alarm["score"],
                    "change_pct": _change_pct(entry["amount"], alarm["expected"]),
                    "kind": alarm["kind"],
                    "new_method": True,  # 하루 비교가 아니라 detection.py 가 알린 것 (비교 기준 설명이 다름)
                }

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
                    "score": anomaly.get("score"),  # AI 점검의 우선순위 계산용 (계산은 그대로, 값만 내보냄)
                    "kind": anomaly.get("kind", "daily"),
                    "kind_text": kind_text(anomaly.get("kind", "daily"), anomaly["direction"]),
                    "basis": KIND_BASIS[anomaly["kind"]] if anomaly.get("new_method") else f"같은 요일 {entry['weeks_used']}번의 중간값",
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
                        "kind": anomaly.get("kind", "daily"),
                        "kind_text": kind_text(anomaly.get("kind", "daily"), anomaly["direction"]),
                        "new_method": bool(anomaly.get("new_method")),
                        "basis": KIND_BASIS[anomaly["kind"]] if anomaly.get("new_method") else None,
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
    "none": "특이사항 없음",  # "정상"이 아니라 "점주가 확인해 특이사항 없음으로 답함"
}
SOLO_REASONS = ("none", "unknown")  # 다른 선택과 함께 저장할 수 없는 값
STORE = "__store__"  # 분류에 속하지 않는 점포 전체 기록용 예약 분류 이름
MAX_MEMO_LENGTH = 300
MAX_RAW_TEXT = 500
MAX_TIME_HINT = 30
SOURCES = ("form", "ai")


def _record_of(record: ReviewedAnomaly | None) -> dict | None:
    if record is None:
        return None
    keys = [k for k in record.reasons.split(",") if k in REASONS]
    return {
        "reasons": keys,
        "reason_labels": [REASONS[k] for k in keys],
        "memo": record.memo,
        "source": record.source or "form",
        "raw_text": record.raw_text or "",
        "time_hint": record.time_hint or "",
        "ai_edited": bool(record.ai_edited),
    }


class ReviewBody(BaseModel):
    category: str
    dates: list[date]
    reasons: list[str] = []
    memo: str = ""
    source: str = "form"  # form(직접 선택) | ai(AI가 정리한 초안을 점주가 확인)
    raw_text: str = ""
    time_hint: str = ""
    ai_edited: bool = False


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
        if category == STORE:  # 점포 전체: 금액 비교 없이 날짜와 기록만
            items.append(
                {
                    "category": STORE,
                    "category_label": "점포 전체",
                    **_day(sales_date),
                    "amount": None,
                    "baseline": None,
                    "change_pct": None,
                    "direction": None,
                    "reviewed_at": record.reviewed_at.isoformat() + "Z",
                    "weeks_used": None,
                    **_record_of(record),
                }
            )
            continue
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
    raw_text = body.raw_text.strip()
    time_hint = body.time_hint.strip()
    solo_mixed = any(r in body.reasons for r in SOLO_REASONS) and len(set(body.reasons)) > 1
    if (
        unknown
        or solo_mixed
        or len(memo) > MAX_MEMO_LENGTH
        or len(raw_text) > MAX_RAW_TEXT
        or len(time_hint) > MAX_TIME_HINT
        or body.source not in SOURCES
    ):
        raise HTTPException(status_code=422, detail={"code": "invalid_record"})
    if body.source == "ai":  # AI 초안은 실제 분류(또는 점포 전체)에만 저장할 수 있습니다
        known_categories = {c for (c,) in db.execute(select(DailySale.category).distinct())} | {STORE}
        if body.category not in known_categories:
            raise HTTPException(status_code=422, detail={"code": "unknown_category"})
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
                db.add(
                    ReviewedAnomaly(
                        category=body.category,
                        sales_date=d,
                        reviewed_at=now,
                        reasons=reasons,
                        memo=memo,
                        source=body.source,
                        raw_text=raw_text,
                        time_hint=time_hint,
                        ai_edited=body.ai_edited,
                    )
                )
            elif body.reasons or memo:
                # 이미 기록된 날짜를 다시 저장하면 내용만 고칩니다. (선택·메모 없이 다시 눌러도 기존 내용은 지우지 않습니다)
                row.reasons, row.memo, row.reviewed_at = reasons, memo, now
                row.source, row.raw_text, row.time_hint, row.ai_edited = body.source, raw_text, time_hint, body.ai_edited
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
