"""무엇을 먼저 확인할지 정하는 우선순위 (SDD 6.2). 점수는 모두 코드가 계산합니다.

초기값입니다. 실제 데이터로 보면서 조정하고, 바꾸면 docs/calculation.md 도 함께 고칩니다.
  priority = 0.5·base + 0.3·impact + 0.2·recency
  base    = min(|탐지 점수|, 10) ÷ 10   (총매출 0.9, 식품군 0.4, 처음 팔린 분류 0.6)
  impact  = min(|금액 − 기준| ÷ 기준이 되는 총매출, 0.5) ÷ 0.5
  recency = 1 ÷ (1 + 0.25 × 며칠 전)
"""
MIN_PRIORITY = 0.35  # 이보다 낮으면 점검에 올리지 않습니다
W_BASE, W_IMPACT, W_RECENCY = 0.5, 0.3, 0.2
BASE_TOTAL = 0.9
BASE_FOOD = 0.4
BASE_NEW_CATEGORY = 0.6  # 평소 한 번도 안 팔리던 분류가 팔린 경우(점수 없음)
IMPACT_CAP = 0.5
FOOD_IMPACT = 0.3
RECENCY_STEP = 0.25


def priority_of(candidate: dict, total_amount: float) -> float:
    num = candidate["_num"]
    kind = candidate["kind"]
    if kind == "total":
        base = BASE_TOTAL
        impact = min(abs(num["amount"] - num["baseline"]) / max(num["baseline"], 1), IMPACT_CAP) / IMPACT_CAP
    elif kind == "food":
        base = BASE_FOOD
        impact = FOOD_IMPACT
    else:
        score = num.get("score")
        base = BASE_NEW_CATEGORY if score is None else min(abs(score), 10) / 10
        impact = min(abs(num["amount"] - num["baseline"]) / max(total_amount, 1), IMPACT_CAP) / IMPACT_CAP
    recency = 1 / (1 + RECENCY_STEP * max(num.get("days_ago", 0), 0))
    return round(W_BASE * base + W_IMPACT * impact + W_RECENCY * recency, 4)


def pick(facts: dict, max_items: int) -> list[dict]:
    """점수가 기준(0.35) 이상인 후보 중 상위 max_items 개. 없으면 빈 목록(= AI를 부르지 않음)."""
    total = facts.get("_total_amount", 0)
    scored = []
    for candidate in facts.get("candidates", []):
        p = priority_of(candidate, total)
        if p >= MIN_PRIORITY:
            scored.append({**candidate, "priority": p})
    scored.sort(
        key=lambda c: (
            -c["priority"],
            -abs(c["_num"]["amount"] - c["_num"]["baseline"]),
            c["name"],
        )
    )
    return scored[:max_items]
