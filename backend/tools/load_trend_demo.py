"""'요즘 뜨는 식품' 시연 데이터를 랩 DB 에 넣습니다 (docs/trends.md). 실제 DB(Supabase)에는 쓰지 않습니다. 대상은 .db 파일(SQLite)만입니다.
실제 SNS 자료가 아니라 지어낸 데이터입니다(화면에 "시연 데이터"로 표시됩니다).

사용법 (backend 폴더에서):
    .venv/Scripts/python tools/load_trend_demo.py --db lab/demo.db
    --gap 을 주면 직전 기간에 수집 실패한 날을 둡니다(비교가 막히는 모습 확인용)
"""
import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app import models, trend, trend_demo  # noqa: E402,F401
from app.db import Base, make_engine, make_session_factory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="요즘 뜨는 식품 시연 데이터 넣기")
    parser.add_argument("--db", type=Path, required=True, help="랩 DB 파일 (.db)")
    parser.add_argument("--gap", action="store_true", help="직전 기간에 수집 실패한 날을 둡니다")
    parser.add_argument("--seed", type=int, default=5)
    args = parser.parse_args()
    if args.db.suffix != ".db" or not args.db.exists():
        raise SystemExit(f"랩 DB(.db)를 찾지 못했어요: {args.db}")
    engine = make_engine(f"sqlite:///{args.db}")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as db:
        result = trend_demo.load(db, trend.kst_today(), args.seed, args.gap)
    print(f"시연 데이터를 넣었어요: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
