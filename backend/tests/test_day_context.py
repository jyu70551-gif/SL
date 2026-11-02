"""6-3: 저장된 장날·공휴일·방학이 알림 목록과 AI 사실 묶음에 '참고'로만 붙는지. 숫자와 이름은 모두 가상입니다.
2026-02-25는 수요일입니다."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import day_context
from app.ai.facts import build_facts
from app.ai.guard import GuardError
from app.models import ScheduleEvent
from tests.conftest import build_app
from tests.test_ai_priority_guard import cand, good, run
from tests.test_anomalies import TODAY, seed
from tests.test_home import TEST_PASSWORD

JUMP = {"담배": (30, 150000), "음료": (17, 30200)}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def add_event(client, kind, name, start, end=None):
    with client.app.state.session_factory() as db:
        db.add(ScheduleEvent(kind=kind, name=name, start_date=start, end_date=end or start, source="owner"))
        db.commit()


def flagged_of(client):
    return client.get("/api/anomalies").json()["items"][0]["flagged"][0]


def test_nothing_saved_means_no_context_and_no_hard_coded_market_day(client):
    seed(client, JUMP)
    flagged = flagged_of(client)
    assert flagged["calendar"] == [] and flagged["calendar_text"] == ""
    with client.app.state.session_factory() as db:
        assert day_context.build(db)(date(2026, 2, 28)) == []  # 예전처럼 3·8일을 장날로 치지 않습니다


def test_saved_market_day_holiday_and_vacation_are_attached_as_reference(client):
    seed(client, JUMP)
    client.post("/api/settings/store", json={"market_days": [5, 25]})
    add_event(client, "holiday", "가상공휴일", TODAY)
    add_event(client, "vacation", "방학", date(2026, 1, 3), date(2026, 2, 28))
    flagged = flagged_of(client)
    assert flagged["calendar"] == ["공휴일(가상공휴일)", "방학", "장날"]
    assert flagged["calendar_text"] == "참고: 이날은 공휴일(가상공휴일), 방학, 장날이에요. 평소와 다를 수 있어요."
    assert flagged["direction"] == "high"  # 알림 자체는 그대로 올라옵니다


def test_other_days_have_no_context(client):
    seed(client, JUMP)
    client.post("/api/settings/store", json={"market_days": [3]})
    add_event(client, "holiday", "다른날", date(2026, 3, 1))
    assert flagged_of(client)["calendar"] == []


def test_ai_facts_context_uses_saved_values(client):
    seed(client, JUMP)
    client.post("/api/settings/store", json={"market_days": [25]})
    add_event(client, "holiday", "가상공휴일", TODAY)
    with client.app.state.session_factory() as db:
        facts = build_facts(db)
    item = next(c for c in facts["candidates"] if c["kind"] == "category")
    assert item["context"] == ["수요일", "공휴일(가상공휴일)", "장날"]


def test_guard_blocks_holiday_or_vacation_as_a_cause_but_allows_mention():
    c = cand()
    run({"headline": "", "items": [good(c, f"담배 {c['amount']}로 비교 기준 {c['baseline']}이에요. 공휴일과 겹쳤는지 확인해 보세요.")]}, [c])
    for cause in ["공휴일이라서", "방학이라", "연휴 때문에"]:
        with pytest.raises(GuardError):
            run({"headline": "", "items": [good(c, f"담배 {c['amount']}로 비교 기준 {c['baseline']}이에요. {cause} 늘었어요.")]}, [c])
