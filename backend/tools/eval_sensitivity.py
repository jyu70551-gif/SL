"""민감도(낮음·보통·높음)별로 "함께" 구성의 성능을 비교합니다 (docs/lab.md). eval_final.py 의 후속입니다.

"함께" = 현재 방식 + 제안 방식 중 하나라도 알리면 알림. 민감도는 두 방식의 기준값을 한꺼번에 바꿉니다.

    민감도   현재 점수 | 매일 팔림 (Shewhart, CUSUM) | 팔린 날 비율 CUSUM | 0원 많음 금액 (Shewhart, CUSUM) | 거의 안 팔림 최소 금액
    낮음      4.0     |        (4.0, 8.0)          |        5.0         |          (4.0, 8.0)            |        5,000원
    보통      3.0     |        (4.0, 5.0)          |        4.0         |          (4.0, 5.0)            |        3,000원   ← 지금까지 평가한 "함께"
    높음      2.5     |        (3.0, 4.0)          |        3.0         |          (3.0, 4.0)            |        2,000원

비교 기준인 "현재"는 지금 앱(점수 3.0)입니다. 앱의 탐지 코드는 바꾸지 않습니다.
현재 방식의 점수 기준 변경은 가장 낮은 기준(2.5)으로 한 번 돌린 뒤 점수로 걸러서 구합니다. (점수는 소수 첫째 자리까지만 저장되어 경계에서 아주 조금 어긋날 수 있음)
가짜 데이터의 가정 아래에서의 연습이며 실제 가게의 정확도가 아닙니다.

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\eval_sensitivity.py --db lab\\eval_seed1.db lab\\eval_seed2.db lab\\eval_seed3.db lab\\eval_seed4.db lab\\eval_seed5.db   (몇 분 걸림)
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

from sqlalchemy import update  # noqa: E402

from app import anomalies  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import DailySale  # noqa: E402
from tools import eval_changepoint as cp  # noqa: E402
from tools import eval_rare as rare_mod  # noqa: E402
from tools.eval_final import COMMON_FROM, DENSE_SCENARIOS, MID_SCENARIOS, RARE_INJECT, TIER_NAMES, TIERS, load, make_shift  # noqa: E402
from tools.make_lab_data import holiday_of  # noqa: E402

DEFAULT_DB = BACKEND / "lab" / "lab.db"
LEVELS = {
    "낮음": {"old": 4.0, "dense": (4.0, 8.0), "occ": 5.0, "mid_amount": (4.0, 8.0), "rare_gap": 5000},
    "보통": {"old": 3.0, "dense": (4.0, 5.0), "occ": 4.0, "mid_amount": (4.0, 5.0), "rare_gap": 3000},
    "높음": {"old": 2.5, "dense": (3.0, 4.0), "occ": 3.0, "mid_amount": (3.0, 4.0), "rare_gap": 2000},
}
LEVEL_NAMES = list(LEVELS)
COLUMNS = ["현재"] + LEVEL_NAMES  # 현재 = 지금 앱 그대로
LOWEST_OLD = min(v["old"] for v in LEVELS.values())


def new_alarms(level: dict, tier: str, qty, amt, dates, rare_series, name) -> list[tuple[int, int]]:
    if tier == "dense":
        scored = cp.score_series([cp.log_value(a) for a in amt], dates)
        return [(i, d) for i, _, d in cp.alarms_of(scored, amt, *level["dense"])]
    if tier == "mid":
        found = list(cp.occurrence_alarms([a > 0 for a in amt], dates, level["occ"]))
        found += [(i, d) for i, _, d in cp.amount_alarms(amt, dates, *level["mid_amount"])]
        return found
    if tier == "rare":
        return [
            (i, 1)
            for i, (q, a) in enumerate(zip(qty, amt))
            if a > 0 and holiday_of(dates[i]) is None
            and rare_mod.is_big_sale(q, a, rare_mod.records_before(rare_series, i, name), rare_mod.records_before(rare_series, i), level["rare_gap"])
        ]
    return []


def raw_current(db) -> dict[tuple[str, date], tuple[int, float | None]]:
    """가장 낮은 기준으로 돌려 (분류, 날짜) -> (방향, 점수). 더 높은 기준은 점수로 걸러서 구합니다."""
    original = anomalies.SCORE_THRESHOLD
    anomalies.SCORE_THRESHOLD = LOWEST_OLD
    try:
        judged = anomalies._analyze(db, anomalies.LEGACY)["judged"]
    finally:
        anomalies.SCORE_THRESHOLD = original
    return {k: (1 if e["anomaly"]["direction"] == "high" else -1, e["anomaly"]["score"]) for k, e in judged.items() if e["anomaly"] is not None}


def current_at(raw: dict, threshold: float) -> dict[tuple[str, date], int]:
    return {k: direction for k, (direction, score) in raw.items() if score is None or abs(score) >= threshold}


def pct(hit: int, total: int) -> str:
    return f"{hit / total * 100:3.0f}%" if total else "  - "


def main() -> int:
    parser = argparse.ArgumentParser(description="민감도별 '함께' 구성 평가")
    parser.add_argument("--db", type=Path, nargs="+", default=[DEFAULT_DB])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    plain = {c: defaultdict(lambda: [0, 0]) for c in COLUMNS}  # 열 -> tier -> [알림, (분류×날)]
    plain_days = [0]
    oneday = {c: defaultdict(lambda: [0, 0]) for c in COLUMNS}  # 열 -> kind -> [잡음, 전체]
    shifts = {c: defaultdict(list) for c in COLUMNS}  # 열 -> (tier, scenario) -> 지연
    for db_path in args.db:
        truth_file = db_path.with_suffix(".truth.json")
        if not db_path.exists() or not truth_file.exists():
            raise SystemExit(f"랩 DB나 정답 기록이 없어요: {db_path}\n먼저 tools/make_lab_data.py 를 실행해 주세요.")
        truth = json.loads(truth_file.read_text(encoding="utf-8"))["정답이 표시된 이상"]
        dates, files, cats = load(db_path)
        index = {d: i for i, d in enumerate(dates)}
        n = len(dates)
        rare_series = {c: list(zip(q, a)) for c, (q, a, tier) in cats.items() if tier == "rare"}
        factory = make_session_factory(make_engine(f"sqlite:///{db_path}"))
        with factory() as db:
            raw = raw_current(db)
        current = {"현재": current_at(raw, 3.0)}
        for name, level in LEVELS.items():
            current[name] = current_at(raw, level["old"])
        events = {(e["category"], date.fromisoformat(e["date"])): e for e in truth}
        after_event = defaultdict(set)
        for (c, d) in events:
            for k in range(8):
                after_event[c].add(d + timedelta(days=k))
        plain_dates = [d for i, d in enumerate(dates) if i >= COMMON_FROM and holiday_of(d) is None and files[d] == "synthetic"]
        plain_days[0] += len(plain_dates)

        def alarm_map(level, c, qty, amt, tier):
            found = defaultdict(set)
            for i, direction in new_alarms(level, tier, qty, amt, dates, rare_series, c):
                found[i].add(direction)
            return found

        new = {name: {c: alarm_map(level, c, qty, amt, tier) for c, (qty, amt, tier) in cats.items() if tier != "none"} for name, level in LEVELS.items()}
        for c, (_, _, tier) in cats.items():
            if tier == "none":
                continue
            for d in plain_dates:
                if d in after_event[c]:
                    continue
                for column in COLUMNS:
                    if column == "현재":
                        flagged = (c, d) in current["현재"]
                    else:
                        flagged = bool(new[column][c].get(index[d])) or (c, d) in current[column]
                    plain[column][tier][1] += 1
                    plain[column][tier][0] += flagged
        for (c, d), e in events.items():
            tier = cats[c][2]
            if tier == "none" or index[d] < COMMON_FROM:
                continue
            want = 1 if e["kind"] == "spike" else -1
            for column in COLUMNS:
                hit = current[column].get((c, d)) == want if column == "현재" else (want in new[column][c].get(index[d], ()) or current[column].get((c, d)) == want)
                oneday[column][e["kind"]][1] += 1
                oneday[column][e["kind"]][0] += hit

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
                        for i in (i for i in range(n) if a2[i] != amt[i]):
                            db.execute(update(DailySale).where(DailySale.sales_date == dates[i], DailySale.category == c).values(amount=int(a2[i]), quantity=int(q2[i])))
                        raw_shifted = raw_current(db)
                        db.rollback()
                        old_delay = {}
                        for column, threshold in [("현재", 3.0)] + [(nm, lv["old"]) for nm, lv in LEVELS.items()]:
                            flags = current_at(raw_shifted, threshold)
                            first = [i for i in window if flags.get((c, dates[i])) == sign]
                            old_delay[column] = first[0] - t0 if first else None
                        shifts["현재"][(tier, scenario)].append(old_delay["현재"])
                        for name, level in LEVELS.items():
                            first = [i for i, direction in new_alarms(level, tier, q2, a2, dates, rare2, c) if i in window and direction == sign]
                            both = [x for x in (min(first) - t0 if first else None, old_delay[name]) if x is not None]
                            shifts[name][(tier, scenario)].append(min(both) if both else None)
        print(f"  완료: {db_path.name}", file=sys.stderr)

    print(f"랩 DB {len(args.db)}개. '낮음/보통/높음'은 '함께' 구성(현재+제안)의 민감도, '현재'는 지금 앱(점수 3.0)\n")
    header = "".join(f"{c:>9}" for c in COLUMNS)
    print("== 1. 평범한 날의 알림 건수")
    days = plain_days[0]
    print(f"  {'':<22}{header}")
    for tier in TIERS:
        print(f"  {TIER_NAMES[tier] + ' (분류×날의 %)':<22}" + "".join(f"{plain[c][tier][0] / plain[c][tier][1] * 100:>8.2f}%" for c in COLUMNS))
    print(f"  {'하루 평균 건수':<22}" + "".join(f"{sum(plain[c][t][0] for t in TIERS) / days:>9.2f}" for c in COLUMNS))
    print(f"  {'한 달(30일) 건수':<22}" + "".join(f"{sum(plain[c][t][0] for t in TIERS) / days * 30:>9.1f}" for c in COLUMNS))

    print("\n== 2. 하루짜리 이상을 그날 알린 비율")
    print(f"  {'':<22}{header}")
    for kind, text in (("spike", "급증"), ("drop", "급감"), ("zero", "품절")):
        print(f"  {text:<22}" + "".join(f"{pct(*oneday[c][kind]):>9}" for c in COLUMNS))

    print(f"\n== 3. 이어지는 변화를 {cp.SHIFT_DAYS}일 안에 알린 비율 (괄호는 중앙 지연 일수)")
    names = {"stockout": "안 팔림(28일 0원)", "rate_down": "팔린 날 60% 줄어듦", "amount_down": "팔릴 때 금액 ×0.6", "amount_up": "팔릴 때 금액 ×1.6", 3: "평소의 3배 판매(하루)", 5: "평소의 5배 판매(하루)"}
    print(f"  {'':<34}" + "".join(f"{c:>14}" for c in COLUMNS))
    for tier in TIERS:
        scenarios = list(DENSE_SCENARIOS) if tier == "dense" else MID_SCENARIOS if tier == "mid" else RARE_INJECT
        for scenario in scenarios:
            cells = []
            for column in COLUMNS:
                delays = shifts[column][(tier, scenario)]
                caught = [d for d in delays if d is not None]
                cells.append(f"{len(caught) / len(delays) * 100:3.0f}% ({median(caught):4.1f})" if caught else "  0% (  - )")
            print(f"  {TIER_NAMES[tier] + ' ' + str(names.get(scenario, scenario)):<34}" + "".join(f"{c:>14}" for c in cells))
    print("\n※ 가짜 데이터의 가정 아래에서의 결과입니다. 변화의 크기·기간은 제가 정한 값이며 실제 가게의 정확도가 아닙니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
