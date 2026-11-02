"""요일 효과를 뺀 뒤 Shewhart(하루 점수) + CUSUM(누적)으로 급증·급감을 탐지하는 실험 (docs/lab.md).

- 앱의 탐지 코드(anomalies.py)는 바꾸지 않습니다. 이 도구 안에서만 계산합니다.
- 값은 로그(금액+1000)로 바꿔 "몇 배" 단위로 봅니다. 그러면 급증·급감이 대칭이 됩니다.
- 요일 효과는 **앞선 날들로만** 추정해서 뺍니다. (같은 요일 기록이 적으면 효과를 0쪽으로 당김)
- 휴일은 알려진 날로 보고 건너뜁니다. (기록에도 넣지 않고 알림도 내지 않음)
- 평소 수준은 최근 84일의 중앙값이라, 수준이 바뀌고 오래 지속되면 새 수준을 평소로 받아들입니다.
- Shewhart: 하루 점수 |z| ≥ c 이고 평소와의 금액 차이 5,000원 이상. CUSUM: 점수를 ±4로 자른 뒤 위·아래 양쪽 누적, 기준 h 초과.
- 평가: ① 정상 구간의 오경보 ② 일부러 만든 수준 이동(며칠~몇 주 지속)을 며칠 만에 알아채나 ③ 하루짜리 이상 재현율.

가짜 데이터의 가정 아래에서의 연습이며, 실제 가게의 정확도가 아닙니다. 수준 이동의 크기와 기간은 제가 정한 값입니다.

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\eval_changepoint.py
    .\\.venv\\Scripts\\python.exe tools\\eval_changepoint.py --db lab\\eval_seed1.db lab\\eval_seed2.db
"""
import argparse
import json
import math
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import DailySale  # noqa: E402
from tools.make_lab_data import holiday_of  # noqa: E402

DEFAULT_DB = BACKEND / "lab" / "lab.db"
OFFSET = 1000.0
WINDOW = 84  # 평소를 정할 때 보는 최근 날 수
MIN_HISTORY = 28
SHRINK = 4  # 요일 효과를 0쪽으로 당기는 정도 (같은 요일 기록이 이만큼일 때 반만 반영)
SCALE_FLOOR = 0.15  # 흩어진 정도의 하한 (로그 단위)
CLIP = 4.0  # CUSUM에 넣는 점수의 상한
K = 0.5  # CUSUM 허용치 (점수 단위)
MIN_GAP = 5000  # Shewhart 알림에 필요한 최소 금액 차이 (현재 방식과 같음)
SHIFT_DAYS = 28
SHIFT_FACTORS = [0.6, 0.8, 1.25, 1.6]
SHEWHART_C = [3.0, 4.0]
CUSUM_H = [4.0, 5.0, 6.0, 8.0]
COMBINED = (4.0, 5.0)  # (Shewhart c, CUSUM h)

# 0원이 많은 분류(팔린 날이 적은 분류)는 두 부분으로 나눠 봅니다: ① 팔렸나 안 팔렸나(횟수) ② 팔린 날의 금액
DENSE_SOLD = 0.9  # 팔린 날 비율이 이 이상이면 거의 매일 팔리는 분류
SPARSE_MIN_SOLD = 0.15  # 이보다 드물게 팔리는 분류는 판단하지 않음 (신호가 너무 적음)
SPARSE_MIN_HISTORY = 15  # ② 팔린 날 금액 기록이 이만큼 쌓이면 판단 시작
SPARSE_WINDOW = 60
P_MIN, P_MAX = 0.05, 0.95  # 팔린 날 비율의 하한·상한
OCCURRENCE_H = [3.0, 4.0, 5.0]
SPARSE_SECOND = [(3.0, None), COMBINED]  # ②에 쓰는 방식
SPARSE_SCENARIOS = {
    "stockout": "안 팔림(28일 내내 0원)",
    "rate_down": "팔린 날이 60% 줄어듦",
    "rate_up": "안 팔리던 날의 60%에 판매 생김",
    "amount_down": "팔릴 때 금액 ×0.6",
    "amount_up": "팔릴 때 금액 ×1.6",
}


def log_value(amount: float) -> float:
    return math.log(amount + OFFSET)


def score_series(values: list[float], dates: list[date], min_history: int = MIN_HISTORY, window: int = WINDOW) -> list[tuple[int, float, float] | None]:
    """날마다 (자리, 점수 z, 평소 금액) 또는 None(휴일·기록 부족). 앞선 날만 사용합니다."""
    scored = [None] * len(values)
    past: list[int] = []
    for i, d in enumerate(dates):
        if holiday_of(d) is not None:
            continue
        recent = past[-window:]
        if len(recent) >= min_history:
            vals = [values[j] for j in recent]
            overall = median(vals)
            by_weekday = defaultdict(list)
            for j in recent:
                by_weekday[dates[j].weekday()].append(values[j] - overall)
            effect = {g: median(v) * len(v) / (len(v) + SHRINK) for g, v in by_weekday.items()}
            residuals = [values[j] - overall - effect[dates[j].weekday()] for j in recent]
            center = median(residuals)
            mad = median(abs(r - center) for r in residuals)
            scale = max(1.4826 * mad, SCALE_FLOOR)
            expected = overall + effect.get(d.weekday(), 0.0)
            scored[i] = (i, (values[i] - expected) / scale, math.exp(expected) - OFFSET)
        past.append(i)
    return scored


def alarms_of(scored, amounts: list[float], shewhart_c: float | None, cusum_h: float | None) -> list[tuple[int, str, int]]:
    """(자리, 'shewhart'|'cusum', 방향 +1/-1). 둘 중 하나라도 넘으면 알림."""
    found = []
    up = down = 0.0
    for i, entry in enumerate(scored):
        if entry is None:
            continue
        _, z, expected_amount = entry
        direction = 1 if z > 0 else -1
        if shewhart_c is not None and abs(z) >= shewhart_c and abs(amounts[i] - expected_amount) >= MIN_GAP:
            found.append((i, "shewhart", direction))
        clipped = max(-CLIP, min(CLIP, z))
        up = max(0.0, up + clipped - K)
        down = max(0.0, down - clipped - K)
        if cusum_h is not None:
            if up > cusum_h:
                found.append((i, "cusum", 1))
                up = 0.0
            if down > cusum_h:
                found.append((i, "cusum", -1))
                down = 0.0
    return found


def occurrence_alarms(sold: list[bool], dates: list[date], h: float) -> list[tuple[int, int]]:
    """① 팔린 날 비율이 바뀌었는지: 비율에 대한 CUSUM. (자리, 방향 +1 늘어남 / -1 줄어듦)
    평소 비율은 앞선 날들에서 구하고, 절반으로 줄거나 (1 - 비율)의 절반만큼 늘어난 경우를 가장 잘 알아채도록 맞춥니다."""
    found = []
    past: list[int] = []
    up = down = 0.0
    for i, d in enumerate(dates):
        if holiday_of(d) is not None:
            continue
        recent = past[-WINDOW:]
        if len(recent) >= MIN_HISTORY:
            p0 = min(P_MAX, max(P_MIN, (sum(sold[j] for j in recent) + 0.5) / (len(recent) + 1)))
            p_down, p_up = p0 * 0.5, p0 + (1 - p0) * 0.5
            if sold[i]:
                down += math.log(p_down / p0)
                up += math.log(p_up / p0)
            else:
                down += math.log((1 - p_down) / (1 - p0))
                up += math.log((1 - p_up) / (1 - p0))
            down, up = max(0.0, down), max(0.0, up)
            if down > h:
                found.append((i, -1))
                down = 0.0
            if up > h:
                found.append((i, 1))
                up = 0.0
        past.append(i)
    return found


def amount_alarms(amounts: list[float], dates: list[date], shewhart_c, cusum_h) -> list[tuple[int, str, int]]:
    """② 팔린 날만 모아서 금액이 바뀌었는지: 위의 요일 효과 제거 + Shewhart/CUSUM. 결과 자리는 원래 날짜의 자리로 돌려줍니다."""
    sold_index = [i for i, a in enumerate(amounts) if a > 0]
    sold_amounts = [amounts[i] for i in sold_index]
    scored = score_series([log_value(a) for a in sold_amounts], [dates[i] for i in sold_index], SPARSE_MIN_HISTORY, SPARSE_WINDOW)
    return [(sold_index[i], kind, direction) for i, kind, direction in alarms_of(scored, sold_amounts, shewhart_c, cusum_h)]


def apply_sparse_scenario(amounts: list[float], dates: list[date], t0: int, scenario: str, rng: random.Random) -> list[float]:
    out = list(amounts)
    earlier_sold = [a for a in amounts[:t0] if a > 0]
    for i in range(t0, t0 + SHIFT_DAYS):
        if holiday_of(dates[i]) is not None:
            continue
        a = out[i]
        if scenario == "stockout":
            out[i] = 0.0
        elif scenario == "rate_down" and a > 0 and rng.random() < 0.6:
            out[i] = 0.0
        elif scenario == "rate_up" and a == 0 and earlier_sold and rng.random() < 0.6:
            out[i] = rng.choice(earlier_sold)
        elif scenario == "amount_down" and a > 0:
            out[i] = a * 0.6
        elif scenario == "amount_up" and a > 0:
            out[i] = a * 1.6
    return out


def sparse_experiment(sparse_series, dates, truth, trials: int, rng: random.Random) -> dict:
    """0원이 많은 분류의 두 부분 방식을 평가합니다. 결과는 합칠 수 있는 개수들로 돌려줍니다."""
    n = len(dates)
    event_days = defaultdict(set)
    for e in truth:
        d = date.fromisoformat(e["date"])
        for k in range(8):
            event_days[e["category"]].add(d + timedelta(days=k))
    result = {"plain": defaultdict(lambda: [0, 0]), "shift": defaultdict(list), "events": defaultdict(lambda: [0, 0])}
    for name, amounts in sparse_series.items():
        sold = [a > 0 for a in amounts]
        usable = [i for i in range(n) if holiday_of(dates[i]) is None and dates[i] not in event_days[name]]
        for h in OCCURRENCE_H:
            alarms = occurrence_alarms(sold, dates, h)
            result["plain"][("occ", h)][0] += sum(1 for i, _ in alarms if dates[i] not in event_days[name])
            result["plain"][("occ", h)][1] += len(usable) - MIN_HISTORY
        for cfg in SPARSE_SECOND:
            alarms = amount_alarms(amounts, dates, *cfg)
            result["plain"][("amt", cfg)][0] += sum(1 for i, _, _ in alarms if dates[i] not in event_days[name])
            result["plain"][("amt", cfg)][1] += len(usable) - SPARSE_MIN_HISTORY
            hit = {i for i, _, _ in alarms}
            for e in truth:
                if e["category"] == name:
                    result["events"][(cfg, e["kind"])][1] += 1
                    result["events"][(cfg, e["kind"])][0] += dates.index(date.fromisoformat(e["date"])) in hit
        for scenario in SPARSE_SCENARIOS:
            for _ in range(trials):
                t0 = rng.randrange(MIN_HISTORY + 20, n - SHIFT_DAYS - 5)
                shifted = apply_sparse_scenario(amounts, dates, t0, scenario, rng)
                sign = 1 if scenario in ("rate_up", "amount_up") else -1
                window = range(t0, t0 + SHIFT_DAYS)
                if scenario.startswith("amount"):
                    for cfg in SPARSE_SECOND:
                        first = [i for i, _, direction in amount_alarms(shifted, dates, *cfg) if i in window and direction == sign]
                        result["shift"][(scenario, "amt", cfg)].append(min(first) - t0 if first else None)
                else:
                    sold_shifted = [a > 0 for a in shifted]
                    for h in OCCURRENCE_H:
                        first = [i for i, direction in occurrence_alarms(sold_shifted, dates, h) if i in window and direction == sign]
                        result["shift"][(scenario, "occ", h)].append(min(first) - t0 if first else None)
    return result


def load(db_path: Path):
    factory = make_session_factory(make_engine(f"sqlite:///{db_path}"))
    with factory() as db:
        rows = list(db.execute(select(DailySale.sales_date, DailySale.category, DailySale.amount)))
    by_cat: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for d, c, a in rows:
        by_cat[c][d] += a
    dates = sorted({d for d, _, _ in rows})
    series = {c: [by_cat[c].get(d, 0.0) for d in dates] for c in by_cat}
    series["총매출"] = [sum(series[c][i] for c in by_cat) for i in range(len(dates))]
    sold = {c: sum(1 for a in v if a > 0) / len(v) for c, v in series.items()}
    dense = {c: v for c, v in series.items() if c == "총매출" or sold[c] >= DENSE_SOLD}  # 거의 매일 팔리는 분류
    sparse = {c: v for c, v in series.items() if c != "총매출" and SPARSE_MIN_SOLD <= sold[c] < DENSE_SOLD}  # 0원이 많은 분류
    return dates, dense, sparse


def run_plain(series, dates, truth, configs):
    """정상 구간 오경보: 일부러 넣은 이상의 7일 뒤까지는 제외하고, 시리즈 하나당 90일에 몇 번인지 셉니다."""
    event_days = defaultdict(set)
    for e in truth:
        d = date.fromisoformat(e["date"])
        for k in range(8):
            event_days[e["category"]].add(d + timedelta(days=k))
            event_days["총매출"].add(d + timedelta(days=k))
    out = {c: [0, 0] for c in configs}  # [알림 수, 본 날 수]
    one_day = {c: defaultdict(lambda: [0, 0]) for c in configs}
    for name, amounts in series.items():
        scored = score_series([log_value(a) for a in amounts], dates)
        for cfg in configs:
            shew, cus = cfg
            alarms = alarms_of(scored, amounts, shew, cus)
            fa = {(i) for i, _, _ in alarms if dates[i] not in event_days[name]}
            out[cfg][0] += len(fa)
            out[cfg][1] += sum(1 for i, s in enumerate(scored) if s is not None and dates[i] not in event_days[name])
            if name != "총매출":
                hit = {(i) for i, _, _ in alarms}
                for e in truth:
                    if e["category"] == name:
                        i = dates.index(date.fromisoformat(e["date"]))
                        if scored[i] is not None:
                            one_day[cfg][e["kind"]][1] += 1
                            one_day[cfg][e["kind"]][0] += i in hit
    return out, one_day


def run_shifts(series, dates, configs, trials_per_factor: int, rng: random.Random):
    """수준 이동(SHIFT_DAYS일 지속)을 넣고, 같은 방향 알림이 그 안에 처음 나온 날까지 걸린 일수를 잽니다."""
    result = {c: defaultdict(list) for c in configs}  # cfg -> factor -> 지연(못 잡으면 None)
    n = len(dates)
    for name, amounts in series.items():
        for factor in SHIFT_FACTORS:
            for _ in range(trials_per_factor):
                t0 = rng.randrange(MIN_HISTORY + 10, n - SHIFT_DAYS - 5)
                shifted = [a * factor if t0 <= i < t0 + SHIFT_DAYS and holiday_of(dates[i]) is None else a for i, a in enumerate(amounts)]
                scored = score_series([log_value(a) for a in shifted], dates)
                sign = 1 if factor > 1 else -1
                for cfg in configs:
                    alarms = alarms_of(scored, shifted, cfg[0], cfg[1])
                    first = [i for i, _, direction in alarms if t0 <= i < t0 + SHIFT_DAYS and direction == sign]
                    result[cfg][factor].append(min(first) - t0 if first else None)
    return result


def label(cfg) -> str:
    shew, cus = cfg
    if shew is not None and cus is not None:
        return f"결합 (Shewhart {shew:g} + CUSUM {cus:g})"
    return f"Shewhart만 {shew:g}" if shew is not None else f"CUSUM만 {cus:g}"


def sparse_label(kind: str, cfg) -> str:
    return f"① 팔린 날 비율 CUSUM {cfg:g}" if kind == "occ" else f"② 팔린 날 금액 {label(cfg)}"


def print_sparse(total: dict, count: int) -> None:
    print(f"\n\n===== 0원이 많은 분류 (팔린 날 비율 {SPARSE_MIN_SOLD:.0%}~{DENSE_SOLD:.0%}, 시리즈 {count}개): 두 부분 방식 =====")
    print("== 정상 구간 오경보 (시리즈 하나당 90일에 몇 번)")
    for key, (alarms, days) in total["plain"].items():
        print(f"  {sparse_label(*key):<46} {alarms / days * 90 if days else 0:5.2f}번 / 90일")
    print(f"\n== 이상을 {SHIFT_DAYS}일 안에 알아챈 비율 (괄호는 알아챈 경우의 중앙 지연 일수)")
    for scenario, text in SPARSE_SCENARIOS.items():
        print(f"  [{text}]")
        for key, delays in total["shift"].items():
            if key[0] != scenario:
                continue
            caught = [d for d in delays if d is not None]
            cell = f"{len(caught) / len(delays) * 100:4.0f}% ({median(caught):>4.1f}일)" if caught else "   0% (   -  )"
            print(f"      {sparse_label(key[1], key[2]):<46} {cell}")
    print("\n== 하루짜리 이상 재현율 (② 팔린 날 금액으로만 판단; 안 팔린 날의 '품절'은 ②로 볼 수 없음)")
    for cfg in SPARSE_SECOND:
        cells = {kind: total["events"][(cfg, kind)] for kind in ("spike", "drop", "zero")}
        text = "  ".join(f"{name} {cells[k][0]}/{cells[k][1]}" for k, name in (("spike", "급증"), ("drop", "급감"), ("zero", "품절")))
        print(f"  ② {label(cfg):<42} {text}")


def main() -> int:
    parser = argparse.ArgumentParser(description="요일 효과 제거 + Shewhart/CUSUM 실험")
    parser.add_argument("--db", type=Path, nargs="+", default=[DEFAULT_DB])
    parser.add_argument("--trials", type=int, default=4, help="분류·크기마다 수준 이동을 넣는 횟수")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    configs = [(c, None) for c in SHEWHART_C] + [(None, h) for h in CUSUM_H] + [COMBINED]
    plain = {c: [0, 0] for c in configs}
    one_day = {c: defaultdict(lambda: [0, 0]) for c in configs}
    shifts = {c: defaultdict(list) for c in configs}
    series_count = 0
    sparse_total = {"plain": defaultdict(lambda: [0, 0]), "shift": defaultdict(list), "events": defaultdict(lambda: [0, 0])}
    sparse_count = 0
    rng = random.Random(args.seed)
    for db_path in args.db:
        truth_file = db_path.with_suffix(".truth.json")
        if not db_path.exists() or not truth_file.exists():
            raise SystemExit(f"랩 DB나 정답 기록이 없어요: {db_path}\n먼저 tools/make_lab_data.py 를 실행해 주세요.")
        truth = json.loads(truth_file.read_text(encoding="utf-8"))["정답이 표시된 이상"]
        dates, series, sparse = load(db_path)
        series_count += len(series)
        sparse_count += len(sparse)
        sp = sparse_experiment(sparse, dates, truth, args.trials, rng)
        for key, (a, b) in sp["plain"].items():
            sparse_total["plain"][key][0] += a
            sparse_total["plain"][key][1] += b
        for key, (a, b) in sp["events"].items():
            sparse_total["events"][key][0] += a
            sparse_total["events"][key][1] += b
        for key, delays in sp["shift"].items():
            sparse_total["shift"][key] += delays
        p, o = run_plain(series, dates, truth, configs)
        s = run_shifts(series, dates, configs, args.trials, rng)
        for cfg in configs:
            plain[cfg][0] += p[cfg][0]
            plain[cfg][1] += p[cfg][1]
            for kind, (h, nn) in o[cfg].items():
                one_day[cfg][kind][0] += h
                one_day[cfg][kind][1] += nn
            for factor, delays in s[cfg].items():
                shifts[cfg][factor] += delays

    print(f"랩 DB {len(args.db)}개, 시리즈(총매출 + 거의 매일 팔리는 분류) {series_count}개, 수준 이동 지속 {SHIFT_DAYS}일\n")
    print("== 정상 구간 오경보 (시리즈 하나당 90일에 몇 번)")
    for cfg in configs:
        alarms, days = plain[cfg]
        print(f"  {label(cfg):<34} {alarms / days * 90:5.2f}번 / 90일")

    print(f"\n== 수준 이동을 {SHIFT_DAYS}일 안에 알아챈 비율 (괄호는 알아챈 경우의 중앙 지연 일수)")
    header = "".join(f"{('×' + str(f)):>16}" for f in SHIFT_FACTORS)
    print(f"  {'방식':<34}{header}")
    for cfg in configs:
        cells = []
        for factor in SHIFT_FACTORS:
            delays = shifts[cfg][factor]
            caught = [d for d in delays if d is not None]
            cells.append(f"{len(caught) / len(delays) * 100:4.0f}% ({median(caught):>4.1f}일)" if caught else f"{0:4.0f}% (   -  )")
        print(f"  {label(cfg):<34}" + "".join(f"{c:>16}" for c in cells))

    print("\n== 하루짜리 이상 재현율 (분류 시리즈만, 앞선 기록이 쌓인 날)")
    for cfg in configs:
        k = one_day[cfg]
        cell = lambda name: f"{k[name][0]}/{k[name][1]}" if name in k else "-"
        print(f"  {label(cfg):<34} 급증 {cell('spike'):>7}  급감 {cell('drop'):>7}  품절 {cell('zero'):>6}")
    print_sparse(sparse_total, sparse_count)
    print("\n※ 가짜 데이터의 가정 아래에서의 결과입니다. 수준 이동의 크기·기간은 제가 정한 값입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
