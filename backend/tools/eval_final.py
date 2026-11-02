"""분류 종류별 탐지 구성(제안)과 현재 앱의 탐지를 같은 가짜 데이터에서 겨룹니다 (docs/lab.md). 마지막 종합 평가입니다.

제안 구성 (거의 안 팔림은 팔린 날 15% 미만, 0원 많음은 15~90%, 거의 매일 팔림은 90% 이상):
  거의 매일 팔림 : 요일 효과 제거 + Shewhart 4 + CUSUM 5            (eval_changepoint.py)
  0원이 많음     : ① 팔린 날 비율 CUSUM(h=4) + ② 팔린 날 금액 (Shewhart 4 + CUSUM 5)
  거의 안 팔림   : 평소보다 많이 팔린 날만 알림, 최소 금액 차이 3,000원  (eval_rare.py)
현재 앱: anomalies.py (같은 요일 비교, 중앙값/MAD, 점수 3.0, 5,000원 이상)

같은 조건으로 비교하려고 모든 분류를 한 번에 평가합니다:
  1. 평범한 날에 하루 평균 몇 건을 알리나 (오경보)
  2. 일부러 넣은 하루짜리 이상(급증·급감·품절)을 같은 날 알리나 (방향이 맞아야 함)
  3. 며칠~몇 주 이어지는 변화를 며칠 만에 알리나 (현재 앱도 같은 DB에서 그대로 돌려 비교)
  4. 거의 안 팔리는 분류의 "많이 팔림"을 알리나

앱의 탐지 코드(anomalies.py)는 바꾸지 않습니다. 가짜 데이터의 가정 아래에서의 연습이며, 변화의 크기·기간은 제가 정한 값입니다.

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\eval_final.py                                  (lab.db 하나, 빠름)
    .\\.venv\\Scripts\\python.exe tools\\eval_final.py --db lab\\eval_seed1.db lab\\eval_seed2.db lab\\eval_seed3.db lab\\eval_seed4.db lab\\eval_seed5.db   (몇 분 걸림)
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select, update  # noqa: E402

from app import anomalies  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import DailySale, SalesUpload  # noqa: E402
from tools import eval_changepoint as cp  # noqa: E402
from tools import eval_rare as rare_mod  # noqa: E402
from tools.make_lab_data import holiday_of  # noqa: E402

DEFAULT_DB = BACKEND / "lab" / "lab.db"
COMMON_FROM = 50  # 두 방식이 모두 판단을 시작한 뒤(앞선 기록이 쌓인 뒤)부터만 비교
RARE_GAP = 3000
TIERS = ("dense", "mid", "rare")
TIER_NAMES = {"dense": "거의 매일 팔림", "mid": "0원이 많음", "rare": "거의 안 팔림"}
DENSE_SCENARIOS = {"×0.6": 0.6, "×0.8": 0.8, "×1.25": 1.25, "×1.6": 1.6}
MID_SCENARIOS = ["stockout", "rate_down", "amount_down", "amount_up"]
RARE_INJECT = [3, 5]


def tier_of(sold_days: int, total_days: int) -> str:
    fraction = sold_days / total_days
    if fraction >= cp.DENSE_SOLD:
        return "dense"
    if fraction >= cp.SPARSE_MIN_SOLD:
        return "mid"
    return "rare" if sold_days > 0 else "none"


def load(db_path: Path):
    factory = make_session_factory(make_engine(f"sqlite:///{db_path}"))
    with factory() as db:
        rows = list(db.execute(select(DailySale.sales_date, DailySale.category, DailySale.quantity, DailySale.amount)))
        files = {u.sales_date: u.filename for u in db.scalars(select(SalesUpload))}
    dates = sorted({r[0] for r in rows})
    cells = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    for d, c, q, a in rows:
        cells[c][d][0] += q
        cells[c][d][1] += a
    cats = {}
    for c, by_date in cells.items():
        qty = [by_date[d][0] if d in by_date else 0 for d in dates]
        amt = [by_date[d][1] if d in by_date else 0.0 for d in dates]
        cats[c] = (qty, amt, tier_of(sum(1 for a in amt if a > 0), len(dates)))
    return dates, files, cats


def new_alarms(tier: str, qty: list[int], amt: list[float], dates: list[date], rare_series: dict, name: str) -> list[tuple[int, int]]:
    """제안 구성의 알림: [(날짜 자리, 방향 +1 많음 / -1 적음)]"""
    if tier == "dense":
        scored = cp.score_series([cp.log_value(a) for a in amt], dates)
        return [(i, d) for i, _, d in cp.alarms_of(scored, amt, *cp.COMBINED)]
    if tier == "mid":
        found = list(cp.occurrence_alarms([a > 0 for a in amt], dates, 4.0))
        found += [(i, d) for i, _, d in cp.amount_alarms(amt, dates, *cp.COMBINED)]
        return found
    if tier == "rare":
        return [
            (i, 1)
            for i, (q, a) in enumerate(zip(qty, amt))
            if a > 0 and holiday_of(dates[i]) is None
            and rare_mod.is_big_sale(q, a, rare_mod.records_before(rare_series, i, name), rare_mod.records_before(rare_series, i), RARE_GAP)
        ]
    return []


def current_flags(db) -> dict[tuple[str, date], int]:
    """현재 앱이 알린 (분류, 날짜) -> 방향(+1 / -1)"""
    judged = anomalies._analyze(db, anomalies.LEGACY)["judged"]
    return {k: (1 if e["anomaly"]["direction"] == "high" else -1) for k, e in judged.items() if e["anomaly"] is not None}


def make_shift(tier: str, scenario, qty: list[int], amt: list[float], dates: list[date], t0: int, rng: random.Random):
    """(바뀐 수량, 바뀐 금액, 알아챌 창 범위, 기대 방향)"""
    if tier == "dense":
        factor = DENSE_SCENARIOS[scenario]
        shifted = [a * factor if t0 <= i < t0 + cp.SHIFT_DAYS and holiday_of(dates[i]) is None else a for i, a in enumerate(amt)]
        return list(qty), shifted, range(t0, t0 + cp.SHIFT_DAYS), 1 if factor > 1 else -1
    if tier == "mid":
        shifted = cp.apply_sparse_scenario(amt, dates, t0, scenario, rng)
        return list(qty), shifted, range(t0, t0 + cp.SHIFT_DAYS), 1 if scenario in ("rate_up", "amount_up") else -1
    k = scenario  # rare: 평소 판매의 k배인 하루
    sold_q = [q for q, a in zip(qty, amt) if a > 0]
    sold_a = [a for a in amt if a > 0]
    q2, a2 = list(qty), list(amt)
    q2[t0], a2[t0] = max(1, round(k * median(sold_q))), k * median(sold_a)
    return q2, a2, range(t0, t0 + 1), 1


def main() -> int:
    parser = argparse.ArgumentParser(description="분류 종류별 탐지 구성 종합 평가")
    parser.add_argument("--db", type=Path, nargs="+", default=[DEFAULT_DB])
    parser.add_argument("--trials", type=int, default=2, help="분류·상황마다 변화를 넣는 횟수")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    methods = ("old", "new", "mix")  # mix = 현재 방식과 제안 방식을 함께 씀 (둘 중 하나라도 알리면 알림)
    plain = {m: defaultdict(lambda: [0, 0]) for m in methods}  # tier -> [알림 수, 평범한 (분류×날) 수]
    plain_days = [0]
    oneday = {m: defaultdict(lambda: [0, 0]) for m in methods}  # (tier, kind) -> [잡음, 전체]
    shifts = {m: defaultdict(list) for m in methods}  # (tier, scenario) -> 지연 목록
    tier_counts = defaultdict(int)
    for db_path in args.db:
        truth_file = db_path.with_suffix(".truth.json")
        if not db_path.exists() or not truth_file.exists():
            raise SystemExit(f"랩 DB나 정답 기록이 없어요: {db_path}\n먼저 tools/make_lab_data.py 를 실행해 주세요.")
        truth = json.loads(truth_file.read_text(encoding="utf-8"))["정답이 표시된 이상"]
        dates, files, cats = load(db_path)
        index = {d: i for i, d in enumerate(dates)}
        n = len(dates)
        rare_series = {c: list(zip(q, a)) for c, (q, a, tier) in cats.items() if tier == "rare"}
        for c, (_, _, tier) in cats.items():
            tier_counts[tier] += 1
        factory = make_session_factory(make_engine(f"sqlite:///{db_path}"))

        with factory() as db:
            old = current_flags(db)
        events = {(e["category"], date.fromisoformat(e["date"])): e for e in truth}
        after_event = defaultdict(set)
        for (c, d) in events:
            for k in range(8):
                after_event[c].add(d + timedelta(days=k))
        plain_dates = [d for i, d in enumerate(dates) if i >= COMMON_FROM and holiday_of(d) is None and files[d] == "synthetic"]
        plain_days[0] += len(plain_dates)

        new = {}
        for c, (qty, amt, tier) in cats.items():
            if tier != "none":
                new[c] = defaultdict(set)
                for i, direction in new_alarms(tier, qty, amt, dates, rare_series, c):
                    new[c][i].add(direction)
        for c, (_, _, tier) in cats.items():
            if tier == "none":
                continue
            for d in plain_dates:
                if d in after_event[c]:
                    continue
                is_new, is_old = bool(new[c].get(index[d])), (c, d) in old
                for m, flagged in (("new", is_new), ("old", is_old), ("mix", is_new or is_old)):
                    plain[m][tier][1] += 1
                    plain[m][tier][0] += flagged
        for (c, d), e in events.items():
            tier = cats[c][2]
            if tier == "none" or index[d] < COMMON_FROM:
                continue
            want = 1 if e["kind"] == "spike" else -1
            hit_new, hit_old = want in new[c].get(index[d], ()), old.get((c, d)) == want
            for m, hit in (("new", hit_new), ("old", hit_old), ("mix", hit_new or hit_old)):
                oneday[m][(tier, e["kind"])][1] += 1
                oneday[m][(tier, e["kind"])][0] += hit

        # 이어지는 변화(거의 안 팔리는 분류는 '많이 팔린 하루')
        with factory() as db:
            for c, (qty, amt, tier) in cats.items():
                if tier == "none":
                    continue
                scenarios = list(DENSE_SCENARIOS) if tier == "dense" else MID_SCENARIOS if tier == "mid" else RARE_INJECT
                for scenario in scenarios:
                    for _ in range(args.trials * (3 if tier == "rare" else 1)):
                        t0 = rng.randrange(cp.MIN_HISTORY + 20, n - cp.SHIFT_DAYS - 5)
                        if holiday_of(dates[t0]) is not None:
                            continue
                        q2, a2, window, sign = make_shift(tier, scenario, qty, amt, dates, t0, rng)
                        rare2 = dict(rare_series)
                        if tier == "rare":
                            rare2[c] = list(zip(q2, a2))
                        first = [i for i, direction in new_alarms(tier, q2, a2, dates, rare2, c) if i in window and direction == sign]
                        delay_new = min(first) - t0 if first else None
                        shifts["new"][(tier, scenario)].append(delay_new)
                        changed = [i for i in range(n) if a2[i] != amt[i]]
                        for i in changed:
                            db.execute(update(DailySale).where(DailySale.sales_date == dates[i], DailySale.category == c).values(amount=int(a2[i]), quantity=int(q2[i])))
                        flags = current_flags(db)
                        db.rollback()
                        first = [i for i in window if flags.get((c, dates[i])) == sign]
                        delay_old = first[0] - t0 if first else None
                        shifts["old"][(tier, scenario)].append(delay_old)
                        both = [x for x in (delay_new, delay_old) if x is not None]
                        shifts["mix"][(tier, scenario)].append(min(both) if both else None)
        print(f"  완료: {db_path.name}", file=sys.stderr)

    print(f"랩 DB {len(args.db)}개. 분류 종류: " + ", ".join(f"{TIER_NAMES[t]} {tier_counts[t]}개" for t in TIERS) + " (한 번도 안 팔린 분류는 판단 대상 아님)\n")

    print("== 1. 평범한 날의 알림 (분류×날짜 중 몇 %를 알렸나 / 하루 평균 몇 건)")
    days = plain_days[0]
    for tier in TIERS:
        row = []
        for m, name in (("old", "현재"), ("new", "제안"), ("mix", "함께")):
            alarms, cells = plain[m][tier]
            row.append(f"{name} {alarms / cells * 100 if cells else 0:5.2f}%")
        print(f"  {TIER_NAMES[tier]:<10} " + "   ".join(row))
    for m, name in (("old", "현재"), ("new", "제안"), ("mix", "함께")):
        total = sum(plain[m][t][0] for t in TIERS)
        print(f"  전체 하루 평균 {name} {total / days if days else 0:.2f}건")

    print("\n== 2. 하루짜리 이상을 그날 알린 비율 (방향이 맞아야 함)")
    for tier in TIERS:
        for kind, text in (("spike", "급증"), ("drop", "급감"), ("zero", "품절")):
            o, nw, mx = oneday["old"][(tier, kind)], oneday["new"][(tier, kind)], oneday["mix"][(tier, kind)]
            if o[1]:
                print(f"  {TIER_NAMES[tier]:<10} {text}  현재 {o[0]}/{o[1]} ({o[0] / o[1] * 100:3.0f}%)   제안 {nw[0]}/{nw[1]} ({nw[0] / nw[1] * 100:3.0f}%)   함께 {mx[0]}/{mx[1]} ({mx[0] / mx[1] * 100:3.0f}%)")
    for kind, text in (("spike", "급증"), ("drop", "급감"), ("zero", "품절")):
        o, nw, mx = ([sum(oneday[m][(t, kind)][i] for t in TIERS) for i in (0, 1)] for m in ("old", "new", "mix"))
        if o[1]:
            print(f"  전체       {text}  현재 {o[0]}/{o[1]} ({o[0] / o[1] * 100:3.0f}%)   제안 {nw[0]}/{nw[1]} ({nw[0] / nw[1] * 100:3.0f}%)   함께 {mx[0]}/{mx[1]} ({mx[0] / mx[1] * 100:3.0f}%)")

    print(f"\n== 3. 이어지는 변화를 {cp.SHIFT_DAYS}일 안에 알린 비율 (괄호는 알린 경우의 중앙 지연 일수). 거의 안 팔림은 '평소의 k배 판매 하루'를 그날 알렸는지")
    names = {"stockout": "안 팔림(28일 0원)", "rate_down": "팔린 날 60% 줄어듦", "amount_down": "팔릴 때 금액 ×0.6", "amount_up": "팔릴 때 금액 ×1.6", 3: "평소의 3배 판매", 5: "평소의 5배 판매"}
    for tier in TIERS:
        print(f"  [{TIER_NAMES[tier]}]")
        scenarios = list(DENSE_SCENARIOS) if tier == "dense" else MID_SCENARIOS if tier == "mid" else RARE_INJECT
        for scenario in scenarios:
            cells = []
            for m in methods:
                delays = shifts[m][(tier, scenario)]
                caught = [d for d in delays if d is not None]
                cells.append(f"{len(caught) / len(delays) * 100 if delays else 0:4.0f}% ({median(caught) if caught else 0:>4.1f}일)" if caught else f"{0:4.0f}% (   -  )")
            print(f"      {names.get(scenario, scenario):<22} 현재 {cells[0]}   제안 {cells[1]}   함께 {cells[2]}   (시도 {len(shifts['new'][(tier, scenario)])}번)")
    print("\n※ 가짜 데이터의 가정 아래에서의 결과입니다. 변화의 크기·기간은 제가 정한 값이며 실제 가게의 정확도가 아닙니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
