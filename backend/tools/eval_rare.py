"""거의 안 팔리는 분류(팔린 날 15% 미만)에서 "평소보다 많이 팔린 날"만 알리는 규칙을 시험합니다 (docs/lab.md).

규칙 (팔린 날에만 판단하며, 앞선 기록만 사용):
 1. 비교 기준 기록: 이 분류의 팔린 날이 5번 이상이면 그 기록, 그보다 적으면 (거의 안 팔리는) 모든 분류의 팔린 날 기록을 합친 것.
 2. 수량: 이 분류 기록이 있으면 "지금까지 최대보다 많고, 평소(중앙값)의 2배 이상". 기록이 적으면 합친 기록의 상위 10% 이상(최소 5개).
 3. 금액: 기준 기록 중 **수량이 많았던 날(상위 25%)의 금액 중앙값 이상**이어야 알림. (수량만 많고 금액이 작은 경우를 거름)
 4. 평소와의 금액 차이가 최소 금액 이상이어야 함 (현재 방식 5,000원. 여기서는 5,000 / 3,000 / 2,000원을 비교).

앱의 탐지 코드(anomalies.py)는 바꾸지 않습니다. 가짜 데이터의 가정 아래에서의 연습이며, "많이 팔림"의 크기는 제가 정한 값입니다.

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\eval_rare.py
    .\\.venv\\Scripts\\python.exe tools\\eval_rare.py --db lab\\eval_seed1.db lab\\eval_seed2.db
"""
import argparse
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import DailySale  # noqa: E402
from tools.make_lab_data import holiday_of  # noqa: E402

DEFAULT_DB = BACKEND / "lab" / "lab.db"
RARE_MAX = 0.15  # 팔린 날 비율이 이보다 낮으면 "거의 안 팔리는" 분류
MIN_OWN_HISTORY = 5
FALLBACK_QUANTITY = 5  # 기준 기록이 너무 적을 때 "많이 팔림"의 최소 수량
POOL_MIN = 5  # 합친 기록이 이만큼은 있어야 기준으로 씀
GAPS = [5000, 3000, 2000]
INJECT_K = [3, 5]  # 평소 판매의 몇 배로 팔린 날을 넣나
TRIALS = 40


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]


def is_big_sale(q: int, a: float, own: list[tuple[int, float]], pooled: list[tuple[int, float]], gap: int) -> bool:
    n = len(own)
    base_amount = median(x[1] for x in own) if own else 0.0
    if n >= MIN_OWN_HISTORY:
        reference = own
        quantities = [x[0] for x in reference]
        if not (q > max(quantities) and q >= 2 * median(quantities)):
            return False
    elif len(pooled) >= POOL_MIN:
        reference = pooled
        if q < max(FALLBACK_QUANTITY, percentile([x[0] for x in reference], 0.9)):
            return False
    else:
        reference = []
        if q < FALLBACK_QUANTITY:
            return False
    if reference:  # 수량이 많았던 날들의 금액만큼은 되어야 한다
        cut = percentile([x[0] for x in reference], 0.75)
        if a < median(x[1] for x in reference if x[0] >= cut):
            return False
    return a - base_amount >= gap


def load(db_path: Path):
    factory = make_session_factory(make_engine(f"sqlite:///{db_path}"))
    with factory() as db:
        rows = list(db.execute(select(DailySale.sales_date, DailySale.category, DailySale.quantity, DailySale.amount)))
    dates = sorted({r[0] for r in rows})
    cells = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    for d, c, q, a in rows:
        cells[c][d][0] += q
        cells[c][d][1] += a
    rare = {}
    for c, by_date in cells.items():
        sold = sum(1 for v in by_date.values() if v[1] > 0)
        if 0 < sold and sold / len(dates) < RARE_MAX:
            rare[c] = [(by_date[d][0], by_date[d][1]) if d in by_date else (0, 0.0) for d in dates]
    return dates, rare


def records_before(series: dict[str, list[tuple[int, float]]], index: int, only: str | None = None):
    names = [only] if only else list(series)
    return [rec for name in names for rec in series[name][:index] if rec[1] > 0]


def describe(rare: dict, dates: list[date]) -> None:
    for name, series in rare.items():
        sold = [r for r in series if r[1] > 0]
        top = sorted(sold, key=lambda r: -r[0])[:3]
        print(
            f"  {name:<12} 팔린 날 {len(sold):>3}/{len(dates)} ({len(sold) / len(dates):.0%})  수량 중앙 {median(r[0] for r in sold):g} 최대 {max(r[0] for r in sold)}  "
            f"금액 중앙 {median(r[1] for r in sold):,.0f}  수량 많았던 3일의 금액 {', '.join(f'{r[1]:,.0f}' for r in top)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="거의 안 팔리는 분류의 '많이 팔림' 알림 실험")
    parser.add_argument("--db", type=Path, nargs="+", default=[DEFAULT_DB])
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    plain = {g: [0, 0, 0] for g in GAPS}  # [알림 수, 팔린 날 수, 본 날 수]
    caught = {(g, k, bucket): [0, 0] for g in GAPS for k in INJECT_K for bucket in ("early", "late")}
    series_count = 0
    for db_path in args.db:
        if not db_path.exists():
            raise SystemExit(f"랩 DB가 없어요: {db_path}\n먼저 tools/make_lab_data.py 를 실행해 주세요.")
        dates, rare = load(db_path)
        series_count += len(rare)
        if db_path == args.db[0]:
            print(f"== 거의 안 팔리는 분류의 판매 기록 ({db_path.name})")
            describe(rare, dates)
        n = len(dates)
        for name, series in rare.items():
            sold_q = [r[0] for r in series if r[1] > 0]
            sold_a = [r[1] for r in series if r[1] > 0]
            for gap in GAPS:
                for i, (q, a) in enumerate(series):
                    if holiday_of(dates[i]) is not None:
                        continue
                    plain[gap][2] += 1
                    if a > 0:
                        plain[gap][1] += 1
                        plain[gap][0] += is_big_sale(q, a, records_before(rare, i, name), records_before(rare, i), gap)
            for k in INJECT_K:
                for _ in range(TRIALS):
                    t0 = rng.randrange(MIN_OWN_HISTORY, n - 5)
                    if holiday_of(dates[t0]) is not None:
                        continue
                    own = records_before(rare, t0, name)
                    q, a = max(1, round(k * median(sold_q))), k * median(sold_a)
                    bucket = "early" if len(own) < MIN_OWN_HISTORY else "late"
                    for gap in GAPS:
                        caught[(gap, k, bucket)][1] += 1
                        caught[(gap, k, bucket)][0] += is_big_sale(q, a, own, records_before(rare, t0), gap)

    print(f"\n랩 DB {len(args.db)}개, 거의 안 팔리는 분류 시리즈 {series_count}개 (팔린 날 {RARE_MAX:.0%} 미만)\n")
    print("== 평범한 판매를 잘못 알린 정도 (최소 금액 차이별)")
    for gap in GAPS:
        alarms, sold_days, days = plain[gap]
        print(f"  {gap:>5,}원 이상  팔린 날 {sold_days}번 중 {alarms}번 알림 ({alarms / sold_days * 100 if sold_days else 0:.1f}%), 시리즈당 90일에 {alarms / days * 90 if days else 0:.2f}번")
    print("\n== '평소 판매의 k배' 판매를 일부러 넣었을 때 알아챈 비율 (early = 이 분류의 팔린 날 기록이 5번 미만)")
    for k in INJECT_K:
        for bucket, text in (("early", "기록 적음(early)"), ("late", "기록 충분(late) ")):
            cells = "  ".join(f"{g:>5,}원 {caught[(g, k, bucket)][0]}/{caught[(g, k, bucket)][1]} ({caught[(g, k, bucket)][0] / caught[(g, k, bucket)][1] * 100 if caught[(g, k, bucket)][1] else 0:3.0f}%)" for g in GAPS)
            print(f"  ×{k} {text}  {cells}")
    print("\n※ 가짜 데이터의 가정 아래에서의 결과입니다. '많이 팔림'의 크기(평소의 3배·5배)는 제가 정한 값입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
