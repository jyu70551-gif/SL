"""AI 응답 검사 (SDD 6.5). 화면에는 이 검사를 통과한 것만 나갑니다.

실패하면 GuardError. 호출한 쪽이 1회 재시도하고, 그래도 안 되면 고정 문구로 대체합니다.
"""
import re

MAX_HEADLINE = 80
MAX_SUMMARY = 160
MAX_QUESTION = 100
MAX_CHECK = 60
MAX_CHECKS = 2
MAX_DETAIL = 100
MAX_TIME_HINT = 20

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# G5: 원인을 단정하는 표현
CAUSAL_RE = re.compile(r"때문|원인(은|이|입니다|이에요|이다)|확실|분명|틀림없|반드시|덕분")
# G6: 데이터가 뒷받침하지 않는 정상·문제없음 판정
JUDGE_RE = re.compile(r"정상|문제\s*없|이상\s*없|걱정\s*(마|없)|괜찮")
# G8: 링크·마크다운·코드·HTML
MARKUP_RE = re.compile(r"https?://|www\.|\]\(|`|<[^>]+>|\*\*|^\s*[#>]", re.MULTILINE)
# G8': 키처럼 생긴 문자열(AI는 키를 알지 못하지만 한 겹 더 막아 둡니다)
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}|api[_\- ]?key|openai", re.IGNORECASE)
# G9: 장날 같은 참고 맥락을 원인처럼 말하는 표현
CONTEXT_CAUSAL_RE = re.compile(r"장날(이라|이어서|이라서|이기|때문|덕|로 인)")
TOTAL_NAME = "총매출"
GENERIC_CATEGORY_NAMES = {"기타"}  # 일반 낱말과 겹치는 분류 이름은 G7에서 제외


class GuardError(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def numbers_in(text: str) -> set[str]:
    return {m.replace(",", "") for m in NUMBER_RE.findall(text)}


def _all_text(values) -> str:
    return " ".join(str(v) for v in values)


def check_text(text: str, reasons: list[str], label: str) -> None:
    if CAUSAL_RE.search(text):
        reasons.append(f"{label}: 원인을 단정하는 표현이 있어요")
    if JUDGE_RE.search(text):
        reasons.append(f"{label}: 정상·문제없음 같은 판정 표현이 있어요")
    if MARKUP_RE.search(text) or SECRET_RE.search(text):
        reasons.append(f"{label}: 링크나 서식이 있어요")
    if CONTEXT_CAUSAL_RE.search(text):
        reasons.append(f"{label}: 참고 맥락을 원인처럼 말했어요")


def validate_briefing(raw: dict, picked: list[dict], facts: dict) -> dict:
    """점검 응답을 검사하고, 화면에 쓸 모양으로 정리해 돌려줍니다."""
    reasons: list[str] = []
    if not isinstance(raw, dict) or not isinstance(raw.get("headline"), str) or not isinstance(raw.get("items"), list):
        raise GuardError(["형식이 맞지 않아요"])

    by_id = {c["id"]: c for c in picked}
    seen: list[str] = []
    items_out: list[dict] = []
    for entry in raw["items"]:
        if not isinstance(entry, dict):
            raise GuardError(["항목 형식이 맞지 않아요"])
        item_id = entry.get("id")
        summary, question, checks = entry.get("summary"), entry.get("question"), entry.get("checks")
        if not all(isinstance(x, str) for x in (item_id, summary, question)) or not isinstance(checks, list):
            raise GuardError(["항목 형식이 맞지 않아요"])
        if item_id not in by_id:
            reasons.append("후보에 없는 항목이에요")
            continue
        if item_id in seen:
            reasons.append("같은 항목이 두 번 있어요")
            continue
        seen.append(item_id)
        candidate = by_id[item_id]
        if candidate["amount"] not in summary:  # G4: 숫자 근거를 먼저
            reasons.append(f"{item_id}: 요약에 금액 근거가 없어요")
        if len(summary) > MAX_SUMMARY or len(question) > MAX_QUESTION:
            reasons.append(f"{item_id}: 너무 길어요")
        clean_checks = [c.strip() for c in checks if isinstance(c, str) and c.strip()][:MAX_CHECKS]
        if any(len(c) > MAX_CHECK for c in clean_checks):
            reasons.append(f"{item_id}: 확인할 일이 너무 길어요")
        items_out.append(
            {
                "id": item_id,
                "kind": candidate["kind"],
                "category": candidate["category"],
                "date": candidate["date"],
                "date_label": candidate["date_label"],
                "name": candidate["name"],
                "direction": candidate["direction"],
                "summary": summary.strip(),
                "question": question.strip(),
                "checks": clean_checks,
            }
        )

    if set(seen) != set(by_id):  # G2: 고른 항목을 빠짐없이, 후보 안에서만
        reasons.append("점검할 항목이 빠졌거나 달라요")
    headline = raw["headline"].strip()
    if len(headline) > MAX_HEADLINE:
        reasons.append("제목 길이가 맞지 않아요")

    text = _all_text([headline] + [f"{i['summary']} {i['question']} {' '.join(i['checks'])}" for i in items_out])
    check_text(text, reasons, "문장")

    # G3: 숫자는 사실 묶음에 있는 것만
    allowed_source = _all_text(
        [facts.get("cutoff", ""), facts.get("analysis_date", ""), facts.get("weekday", "")]
        + [facts.get("total", {}).get(k, "") for k in ("amount", "baseline", "diff", "pct", "basis")]
        + [_all_text(v for k, v in c.items() if k not in ("past_records", "_num", "priority")) for c in picked]
        + [_all_text(p.get("date_label", "") + " " + p.get("time_hint", "") for p in c.get("past_records", [])) for c in picked]
    )
    allowed = numbers_in(allowed_source) | {str(len(picked))}
    extra = numbers_in(text) - allowed
    if extra:
        reasons.append("사실 묶음에 없는 숫자가 있어요")

    # G7: 고르지 않은 분류 이름이나 총매출을 말하면 안 됩니다. (총매출 요약은 참고 정보일 뿐, 항목에 없으면 언급하지 않음)
    mentioned = {c["category"] for c in picked if c["category"]}
    if any(c["kind"] == "total" for c in picked):
        mentioned.add(TOTAL_NAME)
    for name in [*facts.get("categories", []), TOTAL_NAME]:
        if name in GENERIC_CATEGORY_NAMES or name in mentioned:
            continue
        if name in text:
            reasons.append("후보에 없는 분류를 말했어요")
            break

    if reasons:
        raise GuardError(reasons)
    return {"headline": headline, "items": items_out}


def validate_note_detail(detail: str, time_hint: str | None, raw_text: str) -> tuple[str, str]:
    """점주 말을 정리한 문장 검사. 점주가 한 말에 없던 숫자·판정을 덧붙이면 안 됩니다."""
    reasons: list[str] = []
    detail = (detail or "").strip()
    hint = (time_hint or "").strip()
    if len(detail) > MAX_DETAIL:
        reasons.append("정리한 글이 너무 길어요")
    if len(hint) > MAX_TIME_HINT:
        reasons.append("시각 표현이 너무 길어요")
    if MARKUP_RE.search(detail) or MARKUP_RE.search(hint) or SECRET_RE.search(detail + " " + hint):
        reasons.append("링크나 서식이 있어요")
    if numbers_in(detail + " " + hint) - numbers_in(raw_text):
        reasons.append("점주가 말하지 않은 숫자가 있어요")
    if JUDGE_RE.search(detail) and not JUDGE_RE.search(raw_text):
        reasons.append("점주가 말하지 않은 판정 표현이 있어요")
    if reasons:
        raise GuardError(reasons)
    return detail, hint
