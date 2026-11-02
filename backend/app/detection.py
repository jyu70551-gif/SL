"""이어지는 변화와 0원이 많은 분류까지 보는 탐지 (docs/stats-guide.md 1장, docs/calculation.md).

분류를 팔린 날 비율로 세 종류로 나누고, 종류마다 다른 방법을 씁니다.
  거의 매일 팔림 (90% 이상) : 요일 효과를 뺀 뒤 Shewhart(하루 점수) + CUSUM(누적)
  0원이 많음 (15~90%)      : ① 팔린 날 비율 CUSUM  ② 팔린 날의 금액 (위와 같은 방법)
  거의 안 팔림 (15% 미만)   : 평소보다 많이 팔린 날만 알림
기록이 28일 미만이면 판단하지 않습니다. 오늘을 판단할 때는 그보다 앞선 기록만 씁니다.

민감도(낮음/보통/높음)는 아래 LEVELS 의 기준값을 한꺼번에 바꿉니다. 숫자만 바꾸면 전체에 반영됩니다.
tools/eval_*.py (시연 데이터 실험)와 같은 계산이며, 같은 결과가 나오는지는 tests/test_detection.py 가 확인합니다.
"""
import math
from collections import defaultdict
from datetime import date
from statistics import median
from typing import Callable

OFFSET = 1000.0  # 로그를 취하기 전에 더하는 값(원). 0원인 날도 계산하려는 것
WINDOW = 84  # 평소를 정할 때 보는 최근 날 수
MIN_HISTORY = 28  # 앞선 기록이 이만큼 쌓여야 판단
SHRINK = 4  # 요일 효과를 0쪽으로 당기는 정도 (같은 요일 기록이 4번이면 절반만 반영)
SCALE_FLOOR = 0.15  # 흩어진 정도의 하한 (로그 단위)
CLIP = 4.0  # CUSUM에 넣는 점수의 상한
K = 0.5  # CUSUM 허용치 (점수 단위)
MIN_GAP = 5000  # 하루 점수 알림에 필요한 최소 금액 차이(원)

DENSE_SOLD = 0.9  # 팔린 날 비율이 이 이상이면 거의 매일 팔리는 분류
SPARSE_MIN_SOLD = 0.15  # 이보다 드물게 팔리면 "거의 안 팔림"
SPARSE_MIN_HISTORY = 15  # 0원이 많은 분류의 금액: 팔린 날 기록이 이만큼 쌓이면 판단
SPARSE_WINDOW = 60
P_MIN, P_MAX = 0.05, 0.95  # 팔린 날 비율의 하한·상한

MIN_OWN_HISTORY = 5  # 거의 안 팔리는 분류: 이 분류의 팔린 날이 이만큼이면 자기 기록으로 비교
FALLBACK_QUANTITY = 5  # 비교할 기록이 너무 적을 때 "많이 팔림"의 최소 수량
POOL_MIN = 5  # 합친 기록이 이만큼은 있어야 기준으로 씀

DEFAULT_LEVEL = "normal"
LEVELS = {
    "low": {"label": "낮음", "old": 4.0, "dense": (4.0, 8.0), "occ": 5.0, "mid_amount": (4.0, 8.0), "rare_gap": 5000},
    "normal": {"label": "보통", "old": 3.0, "dense": (4.0, 5.0), "occ": 4.0, "mid_amount": (4.0, 5.0), "rare_gap": 3000},
    "high": {"label": "높음", "old": 2.5, "dense": (3.0, 4.0), "occ": 3.0, "mid_amount": (3.0, 4.0), "rare_gap": 2000},
}

Skip = Callable[[date], bool] | None  # True인 날은 기록에도 알림에도 넣지 않음 (예: 알려진 휴일)

# 한 칸(분류×날짜)에 알림이 겹치면 앞쪽을 남깁니다: 하루 점수 > 많이 팔림 > 며칠째 변화 > 이어지는 변화
KIND_RANK = {"daily": 0, "big_sale": 1, "streak": 2, "trend": 3}


def log_value(amount: float) -> float:
    return math.log(amount + OFFSET)


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))]


def tier_of(sold_days: int, total_days: int) -> str:
    """팔린 날 비율로 분류 종류를 정합니다: dense / mid / rare / none(한 번도 안 팔림)"""
    fraction = sold_days / total_days
    if fraction >= DENSE_SOLD:
        return "dense"
    if fraction >= SPARSE_MIN_SOLD:
        return "mid"
    return "rare" if sold_days > 0 else "none"


def score_series(values, dates, min_history=MIN_HISTORY, window=WINDOW, skip: Skip = None):
    """날마다 (자리, 점수 z, 평소 금액) 또는 None(건너뜀·기록 부족). 요일 효과를 빼고, 앞선 날만 사용합니다."""
    scored = [None] * len(values)
    past: list[int] = []
    for i, d in enumerate(dates):
        if skip is not None and skip(d):
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


def alarms_of(scored, amounts, shewhart_c, cusum_h):
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


def occurrence_alarms(sold, dates, h, skip: Skip = None):
    """팔린 날 비율이 바뀌었는지(비율에 대한 CUSUM): [(자리, 방향 +1 늘어남 / -1 줄어듦)]"""
    found = []
    past: list[int] = []
    up = down = 0.0
    for i, d in enumerate(dates):
        if skip is not None and skip(d):
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


def amount_alarms(amounts, dates, shewhart_c, cusum_h, skip: Skip = None):
    """팔린 날만 모아서 금액이 바뀌었는지: [(원래 날짜의 자리, 'shewhart'|'cusum', 방향, 점수, 평소 금액)]"""
    sold_index = [i for i, a in enumerate(amounts) if a > 0]
    sold_amounts = [amounts[i] for i in sold_index]
    scored = score_series([log_value(a) for a in sold_amounts], [dates[i] for i in sold_index], SPARSE_MIN_HISTORY, SPARSE_WINDOW, skip)
    return [(sold_index[i], kind, direction, scored[i][1], scored[i][2]) for i, kind, direction in alarms_of(scored, sold_amounts, shewhart_c, cusum_h)]


def is_big_sale(q, a, own, pooled, gap) -> bool:
    """거의 안 팔리는 분류: 평소보다 많이 팔린 날인가. own/pooled 는 앞선 팔린 날의 [(수량, 금액)]"""
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


def _typical_sold(amounts, i) -> int:
    """앞선 팔린 날(최근 WINDOW일)의 금액 중간값. 없으면 0"""
    sold = [a for a in amounts[max(0, i - WINDOW) : i] if a > 0]
    return round(median(sold)) if sold else 0


def detect(dates, amounts, quantities, level, skip: Skip = None):
    """모든 분류의 알림. 돌려주는 값: {분류: {날짜 자리: {"kind","direction","expected","score"}}}

    dates 는 같은 시각까지의 매출을 올린 날짜들(오래된 순), amounts·quantities 는 분류별로 같은 길이의 목록입니다.
    kind: daily(하루 점수) / trend(이어지는 변화) / streak(팔린 날 비율이 바뀜) / big_sale(거의 안 팔리는 분류가 많이 팔림)
    """
    if level not in LEVELS:
        raise ValueError(f"알 수 없는 민감도: {level}")
    params = LEVELS[level]
    n = len(dates)
    result: dict[str, dict[int, dict]] = {}
    if n <= MIN_HISTORY:
        return result
    tiers = {c: tier_of(sum(1 for a in v if a > 0), n) for c, v in amounts.items()}
    rare_series = {c: list(zip(quantities[c], amounts[c])) for c, t in tiers.items() if t == "rare"}

    def put(found, i, kind, direction, expected, score):
        current = found.get(i)
        if current is None or KIND_RANK[kind] < KIND_RANK[current["kind"]]:
            found[i] = {"kind": kind, "direction": "high" if direction > 0 else "low", "expected": max(0, round(expected)), "score": None if score is None else round(score, 1)}

    for category, amt in amounts.items():
        tier = tiers[category]
        found: dict[int, dict] = {}
        if tier == "dense":
            scored = score_series([log_value(a) for a in amt], dates, skip=skip)
            for i, kind, direction in alarms_of(scored, amt, *params["dense"]):
                put(found, i, "daily" if kind == "shewhart" else "trend", direction, scored[i][2], scored[i][1])
        elif tier == "mid":
            for i, direction in occurrence_alarms([a > 0 for a in amt], dates, params["occ"], skip):
                put(found, i, "streak", direction, _typical_sold(amt, i) if direction < 0 else 0, None)
            for i, kind, direction, z, expected in amount_alarms(amt, dates, *params["mid_amount"], skip=skip):
                put(found, i, "daily" if kind == "shewhart" else "trend", direction, expected, z)
        elif tier == "rare":
            own_pool = rare_series[category]
            for i, (q, a) in enumerate(own_pool):
                if a <= 0 or (skip is not None and skip(dates[i])):
                    continue
                own = [r for r in own_pool[:i] if r[1] > 0]
                pooled = [r for series in rare_series.values() for r in series[:i] if r[1] > 0]
                if is_big_sale(q, a, own, pooled, params["rare_gap"]):
                    put(found, i, "big_sale", 1, median(r[1] for r in own) if own else 0, None)
        if found:
            result[category] = found
    return result
