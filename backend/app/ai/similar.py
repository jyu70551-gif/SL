"""이전 운영 경험 찾기 (SDD 6.8). AI를 부르지 않고 SQL과 고정 문구로 만듭니다.

같은 분류에서 이전에 **같은 방향**의 변화가 있었던 날 중, 점주가 남긴 기록을 최신순 3건까지 보여줍니다.
"이번에도 같은 이유"라고 확정하지 않고, 이전 기록이 있다는 사실과 날짜만 알려 줍니다.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import textfmt as t
from app.ai.facts import past_records
from app.anomalies import _analyze
from app.models import ReviewedAnomaly


def sentence(category: str, direction: str, record: dict) -> str:
    word = "많았던" if direction == "high" else "적었던"
    what = ", ".join(record["labels"]) if record["labels"] else (record["memo"] or "기록")
    return f"이전에 {category} 판매가 {word} {record['date_label']}에 '{what}'{t.eul(what)} 기록하셨어요. 이번에도 같은지 확인해 보세요."


def find_similar(db: Session, category: str, date_iso: str) -> dict:
    try:
        day = date.fromisoformat(date_iso)
    except ValueError:
        return {"direction": None, "items": []}
    analysis = _analyze(db)
    entry = analysis["judged"].get((category, day))
    anomaly = entry["anomaly"] if entry else None
    if not anomaly:
        return {"direction": None, "items": []}
    rows = list(db.scalars(select(ReviewedAnomaly).where(ReviewedAnomaly.category == category)))
    records = past_records(rows, analysis, category, day, anomaly["direction"])
    return {
        "direction": anomaly["direction"],
        "items": [{**record, "text": sentence(category, anomaly["direction"], record)} for record in records],
    }
