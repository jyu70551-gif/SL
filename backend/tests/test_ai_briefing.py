"""Phase 5-2: 오늘의 점검 생성·저장·조회 (SDD 6.3, 7.1). 가짜 LLM만 씁니다."""
import base64
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import config
from app.ai import briefing, fixed
from app.ai import service as service_module
from app.auth import utcnow
from app.models import AiBriefing, AiUsage, ReviewedAnomaly
from tests.ai_fakes import (
    AiError,
    FakeLLM,
    TODAY,
    compliant_briefing,
    get_briefing,
    make_client,  # noqa: F401  (fixture)
    seed_quiet,
    seed_spike,
)
from tests.test_home import WEDNESDAYS, add_day

FIXTURE = Path(__file__).parent / "fixtures" / "sample_2026-02-25.csv"


def rows(client, model):
    with client.app.state.session_factory() as db:
        return list(db.scalars(select(model)))


def ids(view):
    return [item["id"] for item in view["items"]]


def test_requires_login(make_client):
    from fastapi.testclient import TestClient

    client = make_client(FakeLLM())
    bare = TestClient(client.app)
    assert bare.get("/api/ai/briefing").status_code == 401
    assert bare.get("/api/ai/status").status_code == 401


def test_no_upload_yet(make_client):
    client = make_client(FakeLLM())
    assert client.get("/api/ai/briefing").json()["status"] == "none"


def test_ai_briefing_is_created_then_read_from_storage(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    first = client.get("/api/ai/briefing").json()
    assert first["status"] == "pending"  # AI 호출은 기다리지 않고 준비 중으로 답합니다
    view = client.get("/api/ai/briefing").json()
    assert (view["status"], view["mode"]) == ("ready", "ai")
    assert f"cat:담배:{TODAY.isoformat()}" in ids(view)
    assert all(item["summary"] for item in view["items"])
    assert len(llm.calls) == 1  # 한 번만 불렀다


def test_same_facts_are_not_regenerated(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    get_briefing(client)
    for _ in range(3):
        client.get("/api/ai/briefing")
    briefing.ensure_for_latest(client.app.state.session_factory, client.app.state.ai)
    assert len(llm.calls) == 1


def test_quiet_day_makes_no_ai_call(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_quiet(client)
    view = get_briefing(client)
    assert view["quiet"] is True and view["items"] == []
    assert view["headline"] == fixed.QUIET
    assert llm.calls == []  # 억지로 할 일을 만들지 않고, 호출도 하지 않는다


def test_not_enough_history_makes_no_ai_call_and_does_not_judge(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    for day, values in zip(WEDNESDAYS[:2], [{"담배": (10, 50000)}, {"담배": (11, 54000)}]):
        add_day(client, day, values)
    add_day(client, TODAY, {"담배": (50, 900000)})
    view = get_briefing(client)
    assert view["headline"] == fixed.NOT_ENOUGH and view["items"] == []
    assert llm.calls == []


def test_no_key_still_gives_a_fixed_briefing_with_same_shape(make_client):
    client = make_client(None)
    seed_spike(client)
    view = get_briefing(client)
    assert (view["mode"], view["reason"], view["ai"]["state"]) == ("fixed", "no_key", "no_key")
    item = next(i for i in view["items"] if i["kind"] == "category")
    assert set(item) >= {"id", "kind", "category", "date", "summary", "question", "checks", "past"}
    assert item["question"] == fixed.QUESTIONS["high"]


def test_ai_error_falls_back_to_fixed_and_every_screen_stays_200(make_client):
    llm = FakeLLM(default=AiError("server"))
    client = make_client(llm)
    seed_spike(client)
    view = get_briefing(client)
    assert (view["mode"], view["reason"]) == ("fixed", "failed")
    assert view["items"]
    assert client.get("/api/home/summary").status_code == 200
    assert client.get("/api/anomalies").status_code == 200


def test_guard_failure_retries_once_then_falls_back(make_client):
    bad = lambda system, user: {  # noqa: E731
        "headline": "먼저 확인해 보세요.",
        "items": [
            {"id": i["id"], "summary": f"{i['amount']}는 단체 구매 때문이에요.", "question": "확인했나요?", "checks": []}
            for i in json.loads(user)["items"]
        ],
    }
    llm = FakeLLM(default=bad)
    client = make_client(llm)
    seed_spike(client)
    view = get_briefing(client)
    assert (view["mode"], view["reason"]) == ("fixed", "failed")
    assert len(llm.calls) == 2  # 이유를 알려 주고 한 번 더
    assert "거절" in llm.calls[1]["system"]


def test_guard_failure_then_good_second_answer_is_used(make_client):
    state = {"n": 0}

    def flaky(system, user):
        state["n"] += 1
        data = compliant_briefing(system, user)
        if state["n"] == 1:
            data["items"][0]["summary"] += " 원인은 행사예요."
        return data

    llm = FakeLLM(default=flaky)
    client = make_client(llm)
    seed_spike(client)
    view = get_briefing(client)
    assert view["mode"] == "ai" and len(llm.calls) == 2


def test_failed_briefing_is_retried_after_ten_minutes_not_every_request(make_client):
    llm = FakeLLM(responses=[AiError("server")] * 2, default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    assert get_briefing(client)["reason"] == "failed"
    calls_after_failure = len(llm.calls)
    for _ in range(3):
        assert client.get("/api/ai/briefing").json()["reason"] == "failed"
    assert len(llm.calls) == calls_after_failure  # 요청마다 다시 부르지 않는다
    with client.app.state.session_factory() as db:
        row = db.scalar(select(AiBriefing))
        row.created_at = utcnow() - timedelta(minutes=11)
        db.commit()
    client.app.state.ai._fail_count = 0
    client.app.state.ai._open_until = None
    client.get("/api/ai/briefing")
    assert get_briefing(client)["mode"] == "ai"


def test_overwriting_a_date_regenerates_the_briefing(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    get_briefing(client)
    assert len(llm.calls) == 1
    # 2/25 를 평소 수준의 파일로 덮어쓰면 사실이 바뀌어 다시 만들어진다. (업로드 뒤 백그라운드 연결도 함께 확인)
    res = client.post(
        "/api/uploads",
        json={"filename": "s.csv", "content_base64": base64.b64encode(FIXTURE.read_bytes()).decode(), "cutoff_hour": 22, "overwrite": True},
    )
    assert res.status_code == 200
    view = client.get("/api/ai/briefing").json()
    assert f"cat:담배:{TODAY.isoformat()}" not in ids(view)


def test_upload_creates_a_briefing_row_in_the_background(make_client):
    client = make_client(None)
    for day, values in zip(WEDNESDAYS, [{"담배": (10, 50000)}] * 4):
        add_day(client, day, values)
    res = client.post(
        "/api/uploads",
        json={"filename": "s.csv", "content_base64": base64.b64encode(FIXTURE.read_bytes()).decode(), "cutoff_hour": 22},
    )
    assert res.status_code == 200
    assert len(rows(client, AiBriefing)) == 1


def test_briefing_failure_never_breaks_upload(make_client, monkeypatch):
    client = make_client(FakeLLM(default=compliant_briefing))

    def boom(db):
        raise RuntimeError("점검 생성 중 예기치 못한 오류")

    monkeypatch.setattr(briefing, "build_facts", boom)
    res = client.post(
        "/api/uploads",
        json={"filename": "s.csv", "content_base64": base64.b64encode(FIXTURE.read_bytes()).decode(), "cutoff_hour": 22},
    )
    assert res.status_code == 200


def test_recorded_items_disappear_without_regenerating(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    view = get_briefing(client)
    total = [i for i in view["items"] if i["kind"] == "total"]
    category = [i for i in view["items"] if i["kind"] == "category"]
    assert category
    client.post("/api/anomalies/review", json={"category": "담배", "dates": [TODAY.isoformat()], "reasons": ["none"]})
    after = client.get("/api/ai/briefing").json()
    assert f"cat:담배:{TODAY.isoformat()}" not in ids(after)
    assert len(llm.calls) == 1
    if total:  # 총매출 항목은 '점포 전체' 기록으로 닫습니다
        assert any(i["kind"] == "total" for i in after["items"])
        client.post("/api/anomalies/review", json={"category": "__store__", "dates": [TODAY.isoformat()], "reasons": ["unknown"]})
        done = client.get("/api/ai/briefing").json()
        assert done["items"] == [] and done["headline"] == fixed.ALL_DONE


def test_key_added_later_upgrades_the_fixed_briefing(make_client, tmp_path, monkeypatch):
    """키만 .env 에 넣으면 서버를 다시 켜지 않아도 AI 점검으로 바뀐다."""
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "AI_ENV_FILE", env_file)
    llm = FakeLLM(default=compliant_briefing)
    monkeypatch.setattr(service_module, "OpenAILLM", lambda *args, **kwargs: llm)
    client = make_client(None)  # 키 없음으로 시작
    seed_spike(client)
    assert get_briefing(client)["mode"] == "fixed"
    assert llm.calls == []

    env_file.write_text("OPENAI_API_KEY=sk-test-added-later-0000000000\n", encoding="utf-8")
    client.get("/api/ai/briefing")  # 업그레이드가 백그라운드로 시작된다
    view = client.get("/api/ai/briefing").json()
    assert (view["mode"], view["ai"]["state"]) == ("ai", "ready")
    assert len(llm.calls) == 1


def test_fresh_pending_row_blocks_a_second_generation(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    with client.app.state.session_factory() as db:
        db.add(AiBriefing(sales_date=TODAY, status="pending", mode="fixed", facts_hash="x", created_at=utcnow()))
        db.commit()
    briefing.ensure_for_latest(client.app.state.session_factory, client.app.state.ai)
    assert llm.calls == []  # 다른 작업이 만드는 중


def test_stale_pending_row_is_regenerated(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    with client.app.state.session_factory() as db:
        db.add(AiBriefing(sales_date=TODAY, status="pending", mode="fixed", facts_hash="x", created_at=utcnow() - timedelta(minutes=5)))
        db.commit()
    briefing.ensure_for_latest(client.app.state.session_factory, client.app.state.ai)
    assert len(llm.calls) == 1
    assert rows(client, AiBriefing)[0].status == "ok"


def test_monthly_limit_falls_back_to_fixed(make_client, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_CALL_LIMIT", "1")
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    with client.app.state.session_factory() as db:
        db.add(AiUsage(created_at=utcnow(), kind="note", model="m", ok=True))
        db.commit()
    view = get_briefing(client)
    assert (view["mode"], view["ai"]["state"]) == ("fixed", "limit")
    assert llm.calls == []


def test_past_records_are_attached_to_items(make_client):
    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_spike(client)
    # 이전 수요일(1/21)에도 담배가 크게 늘었던 날을 만들고, 점주가 '단체 구매'를 남겼다고 가정
    from datetime import date

    for day in (date(2025, 12, 31), date(2026, 1, 7), date(2026, 1, 14)):
        add_day(client, day, {"담배": (10, 50000), "음료": (17, 30000)})
    add_day(client, date(2026, 1, 21), {"담배": (30, 200000), "음료": (17, 30000)})
    client.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-01-21"], "reasons": ["bulk"], "memo": "회사 행사"})
    view = get_briefing(client)
    item = next(i for i in view["items"] if i["category"] == "담배" and i["date"] == TODAY.isoformat())
    assert item["past"] and item["past"][0]["labels"] == ["단체 구매"]
    assert item["past"][0]["date"] == "2026-01-21"


def test_item_from_an_earlier_day_disappears_once_recorded(make_client):
    """점검 항목은 오늘이 아닌 최근 7일 안의 다른 날짜일 수도 있다. 그 항목도 기록하면 사라져야 한다."""
    from datetime import date

    llm = FakeLLM(default=compliant_briefing)
    client = make_client(llm)
    seed_quiet(client)  # 2/25(수)는 평소 수준
    for day in (date(2026, 2, 3), date(2026, 2, 10), date(2026, 2, 17)):
        add_day(client, day, {"담배": (10, 50000), "음료": (17, 30000)})
    add_day(client, date(2026, 2, 24), {"담배": (30, 200000), "음료": (17, 30000)})  # 화요일 급증
    view = get_briefing(client)
    assert "cat:담배:2026-02-24" in ids(view)

    client.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-02-24"], "reasons": ["none"]})
    after = client.get("/api/ai/briefing").json()
    assert "cat:담배:2026-02-24" not in ids(after)
    undo = client.post("/api/anomalies/unreview", json={"category": "담배", "date": "2026-02-24"})
    assert undo.status_code == 200
    assert "cat:담배:2026-02-24" in ids(client.get("/api/ai/briefing").json())  # 되돌리면 다시 나타남
    assert len(llm.calls) == 1  # 이 모든 과정에서 AI를 다시 부르지 않음


def test_ai_briefing_title_is_built_by_code_not_by_ai(make_client):
    """AI가 쓴 제목(조사 오류나 한 단어일 수 있음)은 쓰지 않고, 코드가 받침을 보고 만든 제목을 쓴다."""
    llm = FakeLLM(default=lambda s, u: {**compliant_briefing(s, u), "headline": "담배"})
    client = make_client(llm)
    seed_spike(client)
    view = get_briefing(client)
    assert view["mode"] == "ai"
    assert view["headline"] != "담배" and "점검해 보세요" in view["headline"]
