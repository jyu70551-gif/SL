"""AI 응답 검사에 쓰는 공통 도구. 화면에는 검사를 통과한 것만 나갑니다.

실패하면 GuardError. 호출한 쪽이 1회 재시도하고, 그래도 안 되면 AI 없이 사실만 보여 줍니다.
"""
import re

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# G5: 원인을 단정하는 표현
CAUSAL_RE = re.compile(r"때문|원인(은|이|입니다|이에요|이다)|확실|분명|틀림없|반드시|덕분")
# G6: 데이터가 뒷받침하지 않는 정상·문제없음 판정
JUDGE_RE = re.compile(r"정상|문제\s*없|이상\s*없|걱정\s*(마|없)|괜찮")
# G8: 링크·마크다운·코드·HTML
MARKUP_RE = re.compile(r"https?://|www\.|\]\(|`|<[^>]+>|\*\*|^\s*[#>]", re.MULTILINE)
# G8': 키처럼 생긴 문자열(AI는 키를 알지 못하지만 한 겹 더 막아 둡니다)
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}|api[_\- ]?key|openai", re.IGNORECASE)
# G9: 장날·공휴일·방학 같은 참고 맥락을 원인처럼 말하는 표현
CONTEXT_CAUSAL_RE = re.compile(r"(장날|공휴일|방학|연휴)(이라|이어서|이라서|이기|때문|덕|로 인)")


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
