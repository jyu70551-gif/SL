"""AI에게 줄 사실 묶음 (SDD 6.1).

기존 계산 함수(`build_sales_detail`, `build_anomaly_list`, `build_home_summary`)를 **읽기만** 합니다.
금액·퍼센트·개수는 코드가 표시용 문자열로 미리 만들어, AI는 그대로 옮겨 쓰기만 합니다.
항목의 `_num` 은 우선순위 계산용 숫자이며 AI에게는 보내지 않습니다.
"""
import hashlib
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import day_context
from app.ai import textfmt as t
from app.anomalies import REASONS, STORE, _analyze, build_anomaly_list
from app.home import build_home_summary
from app.models import ReviewedAnomaly, SalesUpload
from app.sales_detail import build_sales_detail

PAST_MEMO_CHARS = 60
MAX_PAST = 3
HIDDEN_LABEL_KEYS = {"none", "unknown"}  # 이전 기록 문구에는 쓰지 않습니다


def reason_labels(reasons_csv: str, hide_generic: bool = False) -> list[str]:
    keys = [k for k in (reasons_csv or "").split(",") if k in REASONS]
    if hide_generic:
        keys = [k for k in keys if k not in HIDDEN_LABEL_KEYS]
    return [REASONS[k] for k in keys]


def _context(d: date, calendar) -> list[str]:
    """요일과, 점주가 저장한 장날·공휴일·방학. 참고 맥락일 뿐 원인이 아닙니다."""
    return [f"{t.WEEKDAYS[d.weekday()]}요일", *calendar(d)]


def past_records(rows, analysis, category: str, before: date, direction: str) -> list[dict]:
    """같은 분류에서 이전에 같은 방향의 변화가 있었던 날 중, 점주가 남긴 기록 (최신순 최대 3건)."""
    found = []
    for row in sorted((r for r in rows if r.category == category and r.sales_date < before), key=lambda r: r.sales_date, reverse=True):
        entry = analysis["judged"].get((category, row.sales_date))
        anomaly = entry["anomaly"] if entry else None
        if not anomaly or anomaly["direction"] != direction:
            continue
        labels = reason_labels(row.reasons, hide_generic=True)
        if not labels and not row.memo:
            continue
        found.append(
            {
                "date": row.sales_date.isoformat(),
                "date_label": t.date_label(row.sales_date),
                "direction": direction,
                "labels": labels,
                "memo": (row.memo or "")[:PAST_MEMO_CHARS],
                "time_hint": row.time_hint or "",
                "source": row.source or "form",
            }
        )
        if len(found) == MAX_PAST:
            break
    return found


def build_facts(db: Session) -> dict | None:
    latest = db.scalar(select(SalesUpload).order_by(SalesUpload.sales_date.desc()).limit(1))
    if latest is None:
        return None
    today = latest.sales_date
    detail = build_sales_detail(db)
    listing = build_anomaly_list(db)
    home = build_home_summary(db)
    analysis = _analyze(db)
    calendar = day_context.build(db)
    rows = list(db.scalars(select(ReviewedAnomaly)))
    store_recorded = any(r.category == STORE and r.sales_date == today for r in rows)

    test = detail["test"]
    total_amount = detail["today"]["total_amount"]
    facts: dict = {
        "analysis_date": today.isoformat(),
        "weekday": t.WEEKDAYS[today.weekday()],
        "cutoff_hour": latest.cutoff_hour,
        "cutoff": t.hour_label(latest.cutoff_hour),
        "total": {"amount": t.won(total_amount), "status": test["status"], "n": test["n"]},
        "categories": sorted(analysis["categories"]),
        "candidates": [],
        "_total_amount": total_amount,
    }

    # --- 총매출: 탐지 기준을 넘었을 때만 후보
    if test["status"] == "ready":
        center = test["center"]
        diff = total_amount - center
        facts["total"].update(
            verdict=test["verdict"],
            baseline=t.won(center),
            diff=t.signed_won(diff),
            pct=t.pct_text(round(diff / center * 100, 1) if center else None),
            basis=f"이전 {test['n']}일 기록(요일 구분 없음)",
        )
        if test["verdict"] in ("increase", "decrease") and not store_recorded:
            direction = "high" if test["verdict"] == "increase" else "low"
            facts["candidates"].append(
                {
                    "id": f"total:{today.isoformat()}",
                    "kind": "total",
                    "category": "",
                    "name": "총매출",
                    "date": today.isoformat(),
                    "date_label": t.date_label(today),
                    "amount": t.won(total_amount),
                    "baseline": t.won(center),
                    "diff": t.signed_won(diff),
                    "pct": facts["total"]["pct"],
                    "direction": direction,
                    "basis": facts["total"]["basis"],
                    "context": _context(today, calendar),
                    "past_records": [],
                    "_num": {"amount": total_amount, "baseline": center, "score": None, "days_ago": 0},
                }
            )

    # --- 대분류 변화 (최근 7일, 아직 기록하지 않은 것)
    for item in listing.get("items", []):
        for flagged in item["flagged"]:
            d = date.fromisoformat(flagged["date"])
            amount, baseline = flagged["amount"], flagged["baseline"]
            facts["candidates"].append(
                {
                    "id": f"cat:{item['category']}:{flagged['date']}",
                    "kind": "category",
                    "category": item["category"],
                    "name": item["category"],
                    "date": flagged["date"],
                    "date_label": t.date_label(d),
                    "amount": t.won(amount),
                    "baseline": t.won(baseline),
                    "diff": t.signed_won(amount - baseline),
                    "pct": t.pct_text(flagged.get("change_pct")),
                    "direction": flagged["direction"],
                    "basis": flagged.get("basis") or f"같은 요일 {flagged['weeks_used']}번의 중간값",
                    "context": _context(d, calendar),
                    "past_records": past_records(rows, analysis, item["category"], d, flagged["direction"]),
                    "_num": {"amount": amount, "baseline": baseline, "score": flagged.get("score"), "days_ago": (today - d).days},
                }
            )

    # --- 집중 관리 식품군: 과거 관측 범위(최근 4번의 최솟값~최댓값)를 벗어났을 때 (약한 신호)
    if not store_recorded:
        for food in home.get("instant_food", []):
            if food.get("status") != "ready" or food.get("verdict") not in ("high", "low"):
                continue
            facts["candidates"].append(
                {
                    "id": f"food:{food['category']}:{today.isoformat()}",
                    "kind": "food",
                    "category": food["category"],
                    "name": f"{food['category']} 판매 수량",
                    "date": today.isoformat(),
                    "date_label": t.date_label(today),
                    "amount": t.count_text(food["today_quantity"]),
                    "baseline": f"{food['range_min']}~{food['range_max']}개",
                    "diff": "",
                    "pct": "",
                    "direction": food["verdict"],
                    "basis": f"같은 요일 최근 {food['weeks_used']}번의 과거 관측 범위",
                    "context": _context(today, calendar),
                    "past_records": [],
                    "_num": {"amount": food["today_quantity"], "baseline": food["baseline_quantity"], "score": None, "days_ago": 0},
                }
            )

    # --- 전체 상태
    if listing.get("status") == "not_enough" and test["status"] != "ready":
        facts["state"] = "not_enough"
    elif not facts["candidates"]:
        facts["state"] = "quiet"
    else:
        facts["state"] = "items"
    return facts


def facts_hash(facts: dict) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def public_item(candidate: dict) -> dict:
    """AI에게 보낼 항목: 내부 계산용 값(_num)과 priority 를 뺍니다."""
    return {k: v for k, v in candidate.items() if not k.startswith("_") and k != "priority"}
