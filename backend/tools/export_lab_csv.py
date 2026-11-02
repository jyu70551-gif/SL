"""랩 DB를 엑셀로 볼 수 있는 CSV 파일들로 내보냅니다 (docs/lab.md). 읽기만 하며 DB는 바꾸지 않습니다.

만들어지는 파일 (기본: backend/lab/export/):
- 1_금액표.csv       날짜 한 줄, 분류가 열. 한눈에 보기 좋은 표 (실제/가짜 구분, 이상 표시 포함)
- 2_상세.csv         날짜×분류 한 줄씩 (수량, 금액). 필터·피벗용
- 3_정답이상.csv     일부러 넣은 이상(급증·급감·품절) 목록 — 탐지 정답지
- 4_운영기록.csv     가짜로 붙인 점주 운영 상황 기록

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\export_lab_csv.py
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.anomalies import REASONS  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import DailySale, ReviewedAnomaly, SalesUpload  # noqa: E402
from tools.make_lab_data import holiday_of  # noqa: E402

DEFAULT_DB = BACKEND / "lab" / "lab.db"
WEEKDAYS = "월화수목금토일"
KIND_NAMES = {"spike": "급증", "drop": "급감", "zero": "품절(0원)"}


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 엑셀에서 한글이 안 깨짐
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="랩 DB를 CSV로 내보내기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=BACKEND / "lab" / "export")
    args = parser.parse_args()
    if args.db.suffix != ".db" or not args.db.exists():
        raise SystemExit(f"랩 DB를 찾지 못했어요: {args.db}\n먼저 tools/make_lab_data.py 를 실행해 주세요.")
    truth_file = args.db.with_suffix(".truth.json")
    events = json.loads(truth_file.read_text(encoding="utf-8"))["정답이 표시된 이상"] if truth_file.exists() else []
    event_of = {(e["date"], e["category"]): e for e in events}

    factory = make_session_factory(make_engine(f"sqlite:///{args.db}"))
    with factory() as db:
        uploads = {u.sales_date: u for u in db.scalars(select(SalesUpload).order_by(SalesUpload.sales_date))}
        cells = defaultdict(lambda: [0, 0])  # (날짜, 분류) -> [수량, 금액] (상품 줄을 분류별로 합침)
        for d, cat, qty, amount in db.execute(select(DailySale.sales_date, DailySale.category, DailySale.quantity, DailySale.amount)):
            cells[(d, cat)][0] += qty
            cells[(d, cat)][1] += amount
        records = list(db.scalars(select(ReviewedAnomaly).order_by(ReviewedAnomaly.sales_date, ReviewedAnomaly.category)))

    categories = sorted({c for _, c in cells}, key=lambda c: -sum(a for (d, cc), (_, a) in cells.items() if cc == c))  # 매출 큰 분류부터
    args.out.mkdir(parents=True, exist_ok=True)

    def label(d):
        u = uploads[d]
        source = "가짜" if u.filename == "synthetic" else "실제"
        note = holiday_of(d)
        return source, (note or "")

    wide, long_rows = [], []
    for d, u in uploads.items():
        source, holiday = label(d)
        totals = sum(cells[(d, c)][1] for c in categories)
        marks = [f"{c}:{KIND_NAMES[event_of[(d.isoformat(), c)]['kind']]}" for c in categories if (d.isoformat(), c) in event_of]
        wide.append([d.isoformat(), WEEKDAYS[d.weekday()], source, holiday, totals] + [cells[(d, c)][1] for c in categories] + [", ".join(marks)])
        for c in categories:
            e = event_of.get((d.isoformat(), c))
            long_rows.append([d.isoformat(), WEEKDAYS[d.weekday()], source, c, cells[(d, c)][0], cells[(d, c)][1], KIND_NAMES[e["kind"]] if e else ""])
    write_csv(args.out / "1_금액표.csv", ["날짜", "요일", "구분", "휴일", "합계"] + categories + ["일부러 넣은 이상"], wide)
    write_csv(args.out / "2_상세.csv", ["날짜", "요일", "구분", "분류", "수량", "금액", "일부러 넣은 이상"], long_rows)
    write_csv(
        args.out / "3_정답이상.csv",
        ["날짜", "요일", "분류", "종류", "배율(평소 대비)", "평소와의 차이(원)"],
        [
            [e["date"], WEEKDAYS[date.fromisoformat(e["date"]).weekday()], e["category"], KIND_NAMES.get(e["kind"], e["kind"]), e["factor"], e["expected_gap"]]
            for e in sorted(events, key=lambda e: (e["date"], e["category"]))
        ],
    )
    write_csv(
        args.out / "4_운영기록.csv",
        ["날짜", "분류", "이유", "메모", "작성 방식", "기록 시각"],
        [[r.sales_date.isoformat(), r.category, ", ".join(REASONS.get(x, x) for x in r.reasons.split(",") if x), r.memo, {"form": "선택", "ai": "AI가 정리"}.get(r.source, r.source), r.reviewed_at.isoformat(sep=" ", timespec="minutes")] for r in records],
    )
    print(f"내보냈어요: {args.out}")
    for name in sorted(args.out.glob("*.csv")):
        print(f"  {name.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
