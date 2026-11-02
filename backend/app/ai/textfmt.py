"""AI에게 줄 사실 묶음과 고정 문구에 쓰는 표시용 문자열 도우미. (프론트의 format.js와 같은 표기)"""
from datetime import date

WEEKDAYS = "월화수목금토일"


def won(n: float) -> str:
    return f"{int(round(n)):,}원"


def signed_won(n: float) -> str:
    return f"{'+' if n > 0 else '-' if n < 0 else ''}{abs(int(round(n))):,}원"


def pct_text(p: float | None) -> str:
    if p is None:
        return ""
    return f"{'+' if p > 0 else '-' if p < 0 else ''}{abs(p):.1f}%"


def count_text(n: int) -> str:
    return f"{int(n):,}개"


def date_label(d: date) -> str:
    return f"{d.month}월 {d.day}일({WEEKDAYS[d.weekday()]})"


def hour_label(hour: int) -> str:
    if hour == 0:
        return "오전 12시(자정)"
    if hour < 12:
        return f"오전 {hour}시"
    if hour == 12:
        return "오후 12시(정오)"
    return f"오후 {hour - 12}시"


def _has_batchim(word: str) -> bool:
    """마지막 글자에 받침이 있는지. 한글이 아니면 받침 없음으로 봅니다."""
    if not word:
        return False
    code = ord(word[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return False


def _final_consonant(word: str) -> int:
    """마지막 글자의 받침 번호(0=없음, 8=ㄹ). 한글이 아니면 0."""
    if not word:
        return 0
    code = ord(word[-1])
    return (code - 0xAC00) % 28 if 0xAC00 <= code <= 0xD7A3 else 0


def euro(word: str) -> str:
    """'으로/로': 받침이 없거나 ㄹ이면 '로', 그 밖에는 '으로'."""
    return f"{word}로" if _final_consonant(word) in (0, 8) else f"{word}으로"


def eul(word: str) -> str:
    """조사만(을/를). 따옴표 뒤에 붙일 때 씁니다."""
    return "을" if _has_batchim(word) else "를"


def i_ga(word: str) -> str:
    return f"{word}이" if _has_batchim(word) else f"{word}가"


def eun_neun(word: str) -> str:
    return f"{word}은" if _has_batchim(word) else f"{word}는"


def eul_reul(word: str) -> str:
    return f"{word}을" if _has_batchim(word) else f"{word}를"
