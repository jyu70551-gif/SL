"""오늘의 점검 생성·저장·조회 (SDD 6.3).

- 점검은 업로드 직후 백그라운드에서 한 번 만들어 저장합니다. 화면은 저장된 결과를 읽기만 합니다.
- 같은 사실(facts_hash)이면 다시 만들지 않고, 같은 날짜를 덮어써서 사실이 바뀌면 다시 만듭니다.
- 할 일이 없거나(변화 없음) 자료가 부족하면 AI를 부르지 않습니다.
- AI가 불가능하거나 실패하면 같은 모양의 고정 문구로 저장합니다.
"""
import json
import logging
from datetime import date, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.ai import fixed, priority, similar
from app.ai.client import AiError
from app.ai.facts import STORE, build_facts, facts_hash
from app.ai.guard import GuardError, validate_briefing
from app.ai.prompts import SCHEMA_BRIEFING, SYSTEM_BRIEFING, briefing_user_message
from app.ai.service import AiService
from app.auth import utcnow
from app.models import AiBriefing, ReviewedAnomaly, SalesUpload

logger = logging.getLogger("sl.ai")

STALE_PENDING = timedelta(minutes=2)  # 이보다 오래 pending 이면 죽은 작업으로 보고 다시 만듭니다
RETRY_AFTER_FAILURE = timedelta(minutes=10)
MAX_OUTPUT_TOKENS = 1500  # 추론형 모델은 생각하는 데도 토큰을 쓰므로 여유를 둡니다
UPGRADABLE = {"no_key", "off", "limit", "degraded", "key_invalid", "failed"}  # AI로 다시 만들 수 있는 고정 문구 이유
RETRY_REASONS = {"failed", "degraded", "limit"}


def _payload(row: AiBriefing | None) -> dict:
    if row is None or not row.payload:
        return {}
    try:
        return json.loads(row.payload)
    except ValueError:
        return {}


def _attach_past(items: list[dict], picked: list[dict]) -> list[dict]:
    """이전에 점주가 남긴 기록(날짜·라벨)을 항목에 붙입니다. (화면 표시용, AI 호출 없음)"""
    by_id = {c["id"]: c for c in picked}
    for item in items:
        records = by_id.get(item["id"], {}).get("past_records", [])
        item["past"] = [
            {
                "date": r["date"],
                "date_label": r["date_label"],
                "labels": r["labels"],
                "memo": r["memo"],
                "text": similar.sentence(item["category"], r["direction"], r),  # 화면에 그대로 보여줄 고정 문장
            }
            for r in records
        ]
    return items


def _fixed_payload(facts: dict, picked: list[dict], reason: str) -> dict:
    """고정 문구도 AI 점검과 같은 모양(이전 기록 포함)으로 만듭니다."""
    payload = fixed.fixed_payload(facts, picked, reason)
    _attach_past(payload["items"], picked)
    return payload


def _ask_llm(ai: AiService, facts: dict, picked: list[dict]) -> tuple[dict, str]:
    user = briefing_user_message(facts, picked)
    hint = ""
    last: GuardError | None = None
    for _ in range(2):  # 가드에서 막히면 이유를 알려 주고 1회만 다시 시킵니다
        result = ai.generate(
            kind="briefing",
            system=SYSTEM_BRIEFING + hint,
            user=user,
            schema_name="briefing",
            schema=SCHEMA_BRIEFING,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        try:
            return validate_briefing(result.data, picked, facts), result.model
        except GuardError as error:
            ai.record_guard_failure()
            last = error
            hint = "\n\n이전 응답이 거절됐습니다: " + "; ".join(error.reasons) + ". 규칙을 지켜 다시 만드세요."
    raise last  # type: ignore[misc]


def compose(facts: dict, picked: list[dict], ai: AiService) -> tuple[dict, str, str, str]:
    """(payload, mode, status, model). AI를 쓸 수 없거나 실패하면 고정 문구."""
    if facts["state"] == "not_enough" or not picked:
        return _fixed_payload(facts, picked, "quiet"), "fixed", "fixed", ""
    state = ai.state()
    if state != "ready":
        return _fixed_payload(facts, picked, state), "fixed", "fixed", ""
    try:
        data, model = _ask_llm(ai, facts, picked)
        # 제목은 코드가 만듭니다. AI는 항목별 문장(숫자 근거, 질문, 확인할 일)만 씁니다.
        payload = {"headline": fixed.headline_for(picked), "items": _attach_past(data["items"], picked), "quiet": False, "reason": "ai"}
        return payload, "ai", "ok", model
    except (AiError, GuardError) as error:
        code = error.code if isinstance(error, AiError) else "guard"
        logger.warning("AI 점검 생성 실패(%s). 고정 문구로 대체합니다.", code)
        payload = _fixed_payload(facts, picked, "failed")
        payload["error"] = code
        return payload, "fixed", "failed", ""


def _claim(db, sales_date: date, row: AiBriefing | None, facts_hash_value: str, now) -> bool:
    """생성 권한을 얻습니다. 동시에 여러 요청이 와도 한 곳만 통과합니다. (unique 날짜 + pending 상태)"""
    if row is None:
        db.add(AiBriefing(sales_date=sales_date, status="pending", mode="fixed", facts_hash=facts_hash_value, created_at=now))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False
    result = db.execute(
        update(AiBriefing)
        .where(AiBriefing.id == row.id, or_(AiBriefing.status != "pending", AiBriefing.created_at < now - STALE_PENDING))
        .values(status="pending", facts_hash=facts_hash_value, created_at=now)
    )
    db.commit()
    return result.rowcount == 1


def _should_upgrade(row: AiBriefing, ai: AiService, now) -> bool:
    """고정 문구로 저장돼 있는데 지금은 AI를 쓸 수 있으면 AI 점검으로 다시 만듭니다. (예: 키를 나중에 넣은 경우)"""
    payload = _payload(row)
    reason = payload.get("reason", "")
    if row.mode != "fixed" or reason not in UPGRADABLE:
        return False
    if reason in RETRY_REASONS and now - row.created_at < RETRY_AFTER_FAILURE:
        return False
    return ai.state() == "ready"


def ensure_for_latest(session_factory, ai: AiService) -> None:
    """가장 최근에 올린 날짜의 점검을 (필요하면) 만듭니다. 백그라운드에서 호출하며, 예외를 밖으로 내보내지 않습니다."""
    try:
        with session_factory() as db:
            facts = build_facts(db)
            if facts is None:
                return
            sales_date = date.fromisoformat(facts["analysis_date"])
            digest = facts_hash(facts)
            row = db.scalar(select(AiBriefing).where(AiBriefing.sales_date == sales_date))
            now = utcnow()
            if row is not None and row.status == "pending" and now - row.created_at < STALE_PENDING:
                return  # 다른 작업이 만드는 중
            if row is not None and row.facts_hash == digest and row.status in ("ok", "fixed", "failed"):
                if not _should_upgrade(row, ai, now):
                    return
            if not _claim(db, sales_date, row, digest, now):
                return
            picked = priority.pick(facts, ai.settings().max_items)
            payload, mode, status, model = compose(facts, picked, ai)
            current = db.scalar(select(AiBriefing).where(AiBriefing.sales_date == sales_date))
            current.status = status
            current.mode = mode
            current.facts_hash = digest
            current.payload = json.dumps(payload, ensure_ascii=False)
            current.model = model
            current.created_at = utcnow()
            db.commit()
    except Exception:  # noqa: BLE001 - 점검 생성 문제가 업로드나 화면을 막으면 안 됩니다
        logger.exception("AI 점검 생성 중 오류")


def schedule_needed(db, ai: AiService) -> bool:
    """GET 이 백그라운드 생성을 시작해야 하는지."""
    latest = db.scalar(select(SalesUpload.sales_date).order_by(SalesUpload.sales_date.desc()).limit(1))
    if latest is None:
        return False
    row = db.scalar(select(AiBriefing).where(AiBriefing.sales_date == latest))
    now = utcnow()
    if row is None:
        return True
    if row.status == "pending":
        return now - row.created_at >= STALE_PENDING
    return _should_upgrade(row, ai, now)


def read_view(db, ai: AiService) -> dict:
    """저장된 점검을 화면용으로 읽습니다. 이미 기록한 항목은 뺍니다. (AI를 부르지 않습니다)"""
    latest = db.scalar(select(SalesUpload).order_by(SalesUpload.sales_date.desc()).limit(1))
    if latest is None:
        return {"status": "none", "ai": {"state": ai.state()}}
    row = db.scalar(select(AiBriefing).where(AiBriefing.sales_date == latest.sales_date))
    base = {"date": latest.sales_date.isoformat(), "cutoff_hour": latest.cutoff_hour, "ai": {"state": ai.state()}}
    payload = _payload(row)
    if row is None or not payload:
        return {**base, "status": "pending", "mode": "fixed", "headline": "", "items": [], "quiet": False}

    # 항목은 최근 7일의 여러 날짜에 걸칠 수 있으므로, 날짜를 가리지 않고 기록된 것을 모두 봅니다. (기록 표는 작습니다)
    recorded = {(category, day.isoformat()) for category, day in db.execute(select(ReviewedAnomaly.category, ReviewedAnomaly.sales_date))}
    all_items = payload.get("items", [])
    items = []
    for item in all_items:
        key = (item["category"] if item["kind"] == "category" else STORE, item["date"])
        if key not in recorded:
            items.append(item)
    headline = payload.get("headline", "")
    if all_items and not items:
        headline = fixed.ALL_DONE
    return {
        **base,
        "status": "ready",
        "mode": row.mode,
        "reason": payload.get("reason", ""),
        "refreshing": row.status == "pending",
        "headline": headline,
        "items": items,
        "quiet": bool(payload.get("quiet")),
    }
