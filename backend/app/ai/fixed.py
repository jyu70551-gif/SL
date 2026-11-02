"""고정 문구 점검 (SDD 6.6). AI를 쓰지 않고 코드가 같은 모양의 점검을 만듭니다.

AI가 꺼져 있거나, 한도·오류가 있거나, 가드를 통과하지 못했을 때 보이는 문구입니다.
어조는 화면의 다른 문구(salesText.js)와 같고, 원인을 단정하거나 "정상"이라고 판정하지 않습니다.
"""
from app.ai import textfmt as t

NOT_ENOUGH = "비교할 기록이 아직 부족해요. 자료가 더 쌓이면 판매 변화를 확인할 수 있어요."
QUIET = "오늘은 우선 확인할 변화가 없어요."
ALL_DONE = "확인할 점검을 모두 마쳤어요."

QUESTIONS = {
    "high": "행사나 단체 구매, 진열 변경이 있었나요?",
    "low": "입고 지연이나 품절이 있었나요?",
}
CHECKS = {
    "high": ["영수증에서 큰 금액의 단건 결제가 있었는지 보기", "행사·진열 변경 기록 확인하기"],
    "low": ["입고·품절 기록 확인하기", "운영 시간이나 진열 변경 확인하기"],
}


def fixed_summary(c: dict) -> str:
    more_less = "많아요" if c["direction"] == "high" else "적어요"
    kind = c["kind"]
    if kind == "total":
        word = "높아요" if c["direction"] == "high" else "낮아요"
        return f"총매출 {t.euro(c['amount'])} 이전 기록의 비교 기준 {c['baseline']}보다 눈에 띄게 {word}."
    if kind == "food":
        return f"{t.i_ga(c['category'])} {t.euro(c['amount'])} 과거 관측 범위({c['baseline']})보다 {more_less}."
    gap = t.won(abs(c["_num"]["amount"] - c["_num"]["baseline"])) if "_num" in c else c["diff"].lstrip("+-")
    return f"{t.i_ga(c['category'])} {t.euro(c['amount'])} 비교 기준 {c['baseline']}보다 {gap} {more_less}."


def fixed_item(c: dict) -> dict:
    return {
        "id": c["id"],
        "kind": c["kind"],
        "category": c["category"],
        "date": c["date"],
        "date_label": c["date_label"],
        "name": c["name"],
        "direction": c["direction"],
        "summary": fixed_summary(c),
        "question": QUESTIONS[c["direction"]],
        "checks": list(CHECKS[c["direction"]]),
    }


def headline_for(picked: list[dict]) -> str:
    """점검 제목은 AI가 아니라 코드가 받침을 보고 만듭니다. (AI가 쓰면 조사 오류가 생길 수 있어서)"""
    return f"{len(picked)}건을 점검해 보세요. 먼저 {t.eul_reul(picked[0]['name'])} 확인해 보세요."


def fixed_payload(facts: dict, picked: list[dict], reason: str) -> dict:
    """reason: ai_off / no_key / limit / failed / quiet / not_enough ... (화면에는 보이지 않는 이유 표시)"""
    if facts["state"] == "not_enough":
        return {"headline": NOT_ENOUGH, "items": [], "quiet": False, "reason": "not_enough"}
    if not picked:
        return {"headline": QUIET, "items": [], "quiet": True, "reason": "quiet"}
    items = [fixed_item(c) for c in picked]
    return {"headline": headline_for(picked), "items": items, "quiet": False, "reason": reason}
