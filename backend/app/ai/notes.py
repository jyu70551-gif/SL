"""점주의 한마디 → 저장용 초안 (SDD 6.7). 이 모듈은 **아무것도 저장하지 않습니다.** 저장은 점주가 확인한 뒤 기존 기록 주소로 합니다.

AI가 고를 수 있는 값은 서버가 준비한 후보(분류·날짜·운영 상황)뿐이고, 후보 밖의 값은 버리고 되묻기로 바꿉니다.
점주의 글은 "분석할 데이터"일 뿐 지시가 아닙니다. (프롬프트 인젝션을 해도 AI가 할 수 있는 일은 초안을 만드는 것뿐)
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import AiError
from app.ai.facts import STORE
from app.ai.guard import GuardError, validate_note_detail
from app.ai.prompts import SYSTEM_NOTE, note_schema, note_user_message
from app.ai.service import AiService
from app.anomalies import REASONS, build_anomaly_list
from app.models import DailySale, SalesUpload

DATE_CANDIDATES = 14  # 최근 올린 날짜 중 이만큼만 고를 수 있습니다
MAX_OPTIONS = 6
MAX_OUTPUT_TOKENS = 1200
SOLO = ("none", "unknown")  # 다른 운영 상황과 함께 저장할 수 없는 값


def build_candidates(db: Session) -> dict:
    categories = sorted({c for (c,) in db.execute(select(DailySale.category).distinct())})
    dates = [d.isoformat() for d in db.scalars(select(SalesUpload.sales_date).order_by(SalesUpload.sales_date.desc()).limit(DATE_CANDIDATES))]
    return {
        "categories": categories + [STORE],
        "dates": dates,
        "situations": dict(REASONS),
    }


def _normalize_situations(raw) -> list[str]:
    seen: list[str] = []
    for key in raw if isinstance(raw, list) else []:
        if key in REASONS and key not in seen:
            seen.append(key)
    for solo in SOLO:  # none/unknown 은 단독으로만
        if solo in seen:
            return [solo]
    return seen or ["other"]


def _clean_options(raw_question, valid: list[str], labels: dict[str, str] | None = None) -> list[dict]:
    options = []
    if isinstance(raw_question, dict):
        for option in raw_question.get("options", []) or []:
            if isinstance(option, dict) and option.get("value") in valid and all(o["value"] != option["value"] for o in options):
                options.append({"label": str(option.get("label") or option["value"])[:30], "value": option["value"]})
    return options[:MAX_OPTIONS]


def _default_category_options(db: Session, candidates: dict) -> list[dict]:
    flagged = [item["category"] for item in build_anomaly_list(db).get("items", [])]
    names = [c for c in flagged if c in candidates["categories"]] or [c for c in candidates["categories"] if c != STORE]
    names = names[:MAX_OPTIONS - 1] + [STORE]
    return [{"label": "점포 전체" if n == STORE else n, "value": n} for n in names]


def make_draft(db: Session, ai: AiService, *, text: str, hint_date: str | None, hint_category: str | None) -> dict:
    state = ai.state()
    if state != "ready":
        return {"state": state, "status": "unavailable", "draft": None, "question": None}

    candidates = build_candidates(db)
    if not candidates["dates"]:
        return {"state": state, "status": "unavailable", "draft": None, "question": None}
    today = candidates["dates"][0]
    hint_date = hint_date if hint_date in candidates["dates"] else None
    hint_category = hint_category if hint_category in candidates["categories"] else None

    try:
        result = ai.generate(
            kind="note",
            system=SYSTEM_NOTE,
            user=note_user_message(text, candidates, today, hint_date or today),
            schema_name="note_draft",
            schema=note_schema(),
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except AiError as error:
        return {"state": "error", "error": error.code, "status": "unavailable", "draft": None, "question": None}

    data = result.data
    if data.get("status") == "unrelated":
        return {"state": "ready", "status": "unrelated", "draft": None, "question": None}

    category = data.get("category") if data.get("category") in candidates["categories"] else None
    category = category or hint_category
    date = data.get("date") if data.get("date") in candidates["dates"] else None
    date = date or hint_date

    try:
        detail, time_hint = validate_note_detail(data.get("detail", ""), data.get("time_hint"), text)
    except GuardError:
        # 정리한 글이 점주 말에 없는 내용을 담았으면 쓰지 않고, 점주가 쓴 글을 그대로 둡니다.
        detail, time_hint = text.strip()[:100], ""
    detail = detail or text.strip()[:100]

    draft = {
        "category": category,
        "date": date,
        "situations": _normalize_situations(data.get("situations")),
        "detail": detail,
        "time_hint": time_hint,
        "source": "ai",
        "raw_text": text.strip(),
    }

    question = None
    if category is None:
        options = _clean_options(data.get("question"), candidates["categories"]) or _default_category_options(db, candidates)
        question = {"text": "어느 분류에 대한 이야기인가요?", "kind": "category", "options": options}
    elif date is None:
        options = [{"label": d, "value": d} for d in candidates["dates"][:3]]
        question = {"text": "어느 날의 이야기인가요?", "kind": "date", "options": options}

    return {
        "state": "ready",
        "status": "needs_clarification" if question else "ok",
        "draft": draft,
        "question": question,
        "confidence": data.get("confidence", "medium"),
        "candidates": {"categories": candidates["categories"], "dates": candidates["dates"]},
    }
