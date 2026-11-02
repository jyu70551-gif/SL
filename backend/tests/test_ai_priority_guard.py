"""Phase 5-2: 우선순위(코드 계산)와 AI 응답 가드. 합성 데이터라서 DB 없이 확인합니다."""
import copy

import pytest

from app.ai import fixed, priority
from app.ai.guard import GuardError, check_text, validate_briefing, validate_note_detail


def cand(kind="category", category="담배", date="2026-02-25", amount=150000, baseline=50000, score=8.0, days_ago=0, direction="high"):
    """사실 묶음의 후보 하나(가상 숫자)."""
    name = {"total": "총매출", "food": f"{category} 판매 수량"}.get(kind, category)
    unit = "개" if kind == "food" else "원"
    return {
        "id": f"{kind}:{category}:{date}",
        "kind": kind,
        "category": "" if kind == "total" else category,
        "name": name,
        "date": date,
        "date_label": "2월 25일(수)",
        "amount": f"{amount:,}{unit}",
        "baseline": f"{baseline:,}{unit}",
        "diff": f"+{amount - baseline:,}원",
        "pct": "+200.0%",
        "direction": direction,
        "basis": "같은 요일 4번의 중간값",
        "context": ["수요일"],
        "past_records": [],
        "_num": {"amount": amount, "baseline": baseline, "score": score, "days_ago": days_ago},
    }


def facts_with(*candidates, state="items", total=180000):
    return {
        "analysis_date": "2026-02-25",
        "weekday": "수",
        "cutoff": "오전 8시",
        "total": {"amount": f"{total:,}원", "baseline": "100,000원", "diff": "+80,000원", "pct": "+80.0%", "basis": "이전 22일 기록(요일 구분 없음)"},
        "categories": ["담배", "음료", "과자류", "기타"],
        "candidates": list(candidates),
        "state": state,
        "_total_amount": total,
    }


# ---------------------------------------------------------------- 우선순위
def test_no_candidates_picks_nothing():
    assert priority.pick(facts_with(), 2) == []


def test_top_two_by_priority_and_highest_first():
    big = cand(category="담배", amount=200000, baseline=50000, score=9.0)
    mid = cand(category="음료", amount=120000, baseline=60000, score=5.0)
    small = cand(category="과자류", amount=70000, baseline=60000, score=3.2)
    picked = priority.pick(facts_with(small, mid, big), 2)
    assert [c["category"] for c in picked] == ["담배", "음료"]
    assert picked[0]["priority"] >= picked[1]["priority"]


def test_low_priority_is_dropped():
    weak = cand(amount=52000, baseline=50000, score=0.2, days_ago=6)
    assert priority.pick(facts_with(weak), 2) == []


def test_older_change_ranks_below_same_size_recent_change():
    recent = cand(category="담배", days_ago=0)
    older = cand(category="음료", days_ago=5)
    picked = priority.pick(facts_with(older, recent), 2)
    assert picked[0]["category"] == "담배"


def test_new_category_without_score_still_considered():
    new = cand(score=None, amount=80000, baseline=0)
    assert len(priority.pick(facts_with(new), 2)) == 1


def test_total_ranks_high_and_respects_max_items():
    total = cand(kind="total", category="", amount=300000, baseline=100000, score=None)
    a, b = cand(category="담배"), cand(category="음료")
    picked = priority.pick(facts_with(a, b, total), 1)
    assert [c["kind"] for c in picked] == ["total"]


# ---------------------------------------------------------------- 가드
def good(c, summary=None):
    return {
        "id": c["id"],
        "summary": summary or f"{c['name']} {c['amount']}로 비교 기준 {c['baseline']}과 차이가 있어요.",
        "question": "확인해 보셨나요?",
        "checks": ["기록 확인하기"],
    }


def run(raw, picked, facts=None):
    return validate_briefing(raw, picked, facts or facts_with(*picked))


def test_good_response_passes_and_is_normalized():
    c = cand()
    out = run({"headline": "먼저 확인해 보세요.", "items": [good(c)]}, [c])
    assert out["items"][0]["category"] == "담배" and out["items"][0]["checks"] == ["기록 확인하기"]


@pytest.mark.parametrize(
    "bad_summary",
    [
        "담배 150,000원은 단체 구매 때문에 늘었어요.",  # G5
        "담배 150,000원이고 원인은 행사예요.",  # G5
        "담배 150,000원인 것이 확실해요.",  # G5
        "담배 150,000원이고 문제없어요.",  # G6
        "담배 150,000원은 정상이에요.",  # G6
        "담배 150,000원이고 이상 없어요.",  # G6
        "담배 150,000원이에요. 자세한 내용은 https://example.com 에서 보세요.",  # G8
        "담배 **150,000원**이에요.",  # G8
        "담배 150,000원이고 장날이라서 늘었어요.",  # G9
        "담배 150,000원이고 평소의 3배예요.",  # G3: 사실 묶음에 없는 숫자
    ],
)
def test_guard_rejects_banned_phrases_and_unknown_numbers(bad_summary):
    c = cand()
    with pytest.raises(GuardError):
        run({"headline": "먼저 확인해 보세요.", "items": [good(c, bad_summary)]}, [c])


def test_summary_without_the_amount_is_rejected():
    c = cand()
    with pytest.raises(GuardError):
        run({"headline": "확인해 보세요.", "items": [good(c, "담배가 평소보다 많아요.")]}, [c])


def test_unknown_id_duplicate_and_missing_items_are_rejected():
    a, b = cand(category="담배"), cand(category="음료")
    with pytest.raises(GuardError):
        run({"headline": "확인해 보세요.", "items": [good(a), {**good(b), "id": "cat:없는것:2026-02-25"}]}, [a, b])
    with pytest.raises(GuardError):
        run({"headline": "확인해 보세요.", "items": [good(a), good(a)]}, [a, b])
    with pytest.raises(GuardError):
        run({"headline": "확인해 보세요.", "items": [good(a)]}, [a, b])  # 고른 항목이 빠짐


def test_mentioning_a_category_that_was_not_picked_is_rejected():
    c = cand(category="담배")
    summary = f"담배 {c['amount']}로 비교 기준 {c['baseline']}이에요. 음료도 같이 봐요."
    with pytest.raises(GuardError):
        run({"headline": "확인해 보세요.", "items": [good(c, summary)]}, [c])


def test_generic_word_that_is_also_a_category_name_is_allowed():
    c = cand(category="담배")
    summary = f"담배 {c['amount']}로 비교 기준 {c['baseline']}이에요. 기타 사항도 확인해 보세요."
    run({"headline": "확인해 보세요.", "items": [good(c, summary)]}, [c])  # '기타'는 일반 낱말과 겹쳐 제외


def test_malformed_shapes_are_rejected():
    c = cand()
    for raw in ({}, {"headline": 3, "items": []}, {"headline": "a", "items": [3]}, {"headline": "a", "items": [{"id": c["id"]}]}):
        with pytest.raises(GuardError):
            run(raw, [c])


def test_too_long_text_is_rejected():
    c = cand()
    with pytest.raises(GuardError):
        run({"headline": "가" * 81, "items": [good(c)]}, [c])
    long_summary = f"담배 {c['amount']} " + "가" * 200
    with pytest.raises(GuardError):
        run({"headline": "확인해 보세요.", "items": [good(c, long_summary)]}, [c])


def test_context_may_be_mentioned_but_not_as_a_cause():
    c = cand()
    ok = f"담배 {c['amount']}로 비교 기준 {c['baseline']}이에요. 장날과 겹쳤는지도 확인해 보세요."
    run({"headline": "확인해 보세요.", "items": [good(c, ok)]}, [c])


# ---------------------------------------------------------------- 점주 글 정리 검사
def test_note_detail_may_not_add_numbers_or_judgements():
    assert validate_note_detail("입고 지연", "오전 7시경", "오늘 입고가 늦었고 7시쯤 다 나갔어")[0] == "입고 지연"
    with pytest.raises(GuardError):
        validate_note_detail("입고 지연으로 30개 품절", None, "입고가 늦었어")
    with pytest.raises(GuardError):
        validate_note_detail("입고 지연, 문제없음", None, "입고가 늦었어")
    validate_note_detail("정상 입고 확인", None, "정상 입고됐어")  # 점주가 한 말이면 그대로 둡니다


# ---------------------------------------------------------------- 고정 문구
def test_fixed_texts_obey_the_same_rules_as_ai_text():
    """고정 문구도 단정·판정 표현을 쓰지 않는다."""
    for direction in ("high", "low"):
        for c in (cand(direction=direction), cand(kind="total", category="", direction=direction), cand(kind="food", category="간편식사", direction=direction)):
            item = fixed.fixed_item(copy.deepcopy(c))
            reasons: list[str] = []
            check_text(f"{item['summary']} {item['question']} {' '.join(item['checks'])}", reasons, "고정")
            assert reasons == []
            assert c["amount"] in item["summary"]
    for text in (fixed.NOT_ENOUGH, fixed.QUIET, fixed.ALL_DONE):
        reasons: list[str] = []
        check_text(text, reasons, "고정")
        assert reasons == []


def test_fixed_payload_states():
    c = cand()
    f = facts_with(c)
    assert fixed.fixed_payload({**f, "state": "not_enough"}, [], "x")["headline"] == fixed.NOT_ENOUGH
    assert fixed.fixed_payload({**f, "state": "quiet"}, [], "x")["quiet"] is True
    payload = fixed.fixed_payload(f, [c], "no_key")
    assert payload["items"][0]["question"] == fixed.QUESTIONS["high"] and payload["reason"] == "no_key"


def test_total_sales_cannot_be_mentioned_unless_it_is_a_picked_item():
    """총매출 요약은 참고 정보다. 항목에 없는데 제목이나 요약에서 말하면 막는다. (실제 응답에서 발견)"""
    c = cand(category="담배")
    with pytest.raises(GuardError):
        run({"headline": "먼저 총매출과 담배를 확인해 보세요.", "items": [good(c)]}, [c])
    total = cand(kind="total", category="", amount=300000, baseline=100000, score=None)
    run({"headline": "먼저 총매출과 담배를 확인해 보세요.", "items": [good(c), good(total)]}, [c, total])  # 총매출 항목이 있으면 허용


def test_headline_may_be_empty_and_is_built_by_code():
    c = cand()
    out = run({"headline": "", "items": [good(c)]}, [c])
    assert out["headline"] == ""  # AI가 비워 둬도 통과. 화면에 쓰는 제목은 briefing.compose 가 코드로 만든다
    assert fixed.headline_for([c]) == "1건을 점검해 보세요. 먼저 담배를 확인해 보세요."
    assert fixed.headline_for([cand(kind="total", category="")]).endswith("먼저 총매출을 확인해 보세요.")
