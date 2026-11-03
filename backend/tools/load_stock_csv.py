"""가짜 입출고 자료를 랩 DB에 넣습니다 (docs/stock.md). 실제 DB(Supabase)에는 쓰지 않습니다. 대상은 .db 파일(SQLite)만입니다.

사용법 (backend 폴더에서):
    .venv/Scripts/python tools/load_stock_csv.py --db lab/demo.db --end 2026-02-25
CSV 를 따로 주지 않으면 가짜 자료(make_stock_data)를 --end 날짜까지 40일치 만들어 넣습니다.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app import models, stock  # noqa: E402,F401  (models 를 불러와야 create_all 이 표를 압니다)
from app.db import Base, make_engine, make_session_factory  # noqa: E402
from tools import make_stock_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="가짜 입출고 자료를 랩 DB에 넣기")
    parser.add_argument("--db", type=Path, required=True, help="랩 DB 파일 (.db)")
    parser.add_argument("--csv", type=Path, help="입출고 CSV (없으면 가짜 자료를 만듭니다)")
    parser.add_argument("--end", type=date.fromisoformat, default=date.today(), help="가짜 자료의 마지막 날짜")
    parser.add_argument("--days", type=int, default=40)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()
    if args.db.suffix != ".db" or not args.db.exists():
        raise SystemExit(f"랩 DB(.db)를 찾지 못했어요: {args.db}")
    if args.csv:
        records = stock.parse_stock_csv(args.csv.read_text(encoding="utf-8"))
    else:
        rows, _ = make_stock_data.build(args.seed, args.days, start=args.end - timedelta(days=args.days - 1))
        records = stock.parse_stock_csv(make_stock_data.to_csv(rows))
    engine = make_engine(f"sqlite:///{args.db}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as db:
        saved = stock.save_records(db, records)
    print(f"{saved}줄을 {args.db.name} 에 넣었어요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
