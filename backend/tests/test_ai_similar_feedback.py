"""Phase 5-4: 이전 기록 찾기, 평가, 지표, 보안 (SDD 6.8, 6.10, 9)."""
import logging
from datetime import date

import pytest

from tests.ai_fakes import FakeLLM, TODAY, compliant_briefing, get_briefing, make_client, seed_spike  # noqa: F401
from tests.test_home import add_day

SECRET = "sk-test-SECRET-ABCDEFGHIJ"


def base_days(client, days):
    for day in days:
        add_day(client, day, {"담배": (10, 50000), "음료": (17, 30000)})


def spike(client, day, amount=200000):
    add_day(client, day, {"담배": (30, amount), "음료": (17, 30000)})


@pytest.fixture
def client(make_client):
    c = make_client(FakeLLM(default=compliant_briefing))
    # 12/31, 1/7, 1/14 평소 → 1/21 급증 → 1/28, 2/4, 2/11, 2/18 평소 → 2/25(오늘) 급증
    base_days(c, [date(2025, 12, 31), date(2026, 1, 7), date(2026, 1, 14)])
    spike(c, date(2026, 1, 21))
    base_days(c, [date(2026, 1, 28), date(2026, 2, 4), date(2026, 2, 11), date(2026, 2, 18)])
    spike(c, TODAY, 180000)
    return c


def review(client, day, **body):
    return client.post("/api/anomalies/review", json={"category": "담배", "dates": [day], **body})


def similar(client, day=TODAY.isoformat(), category="담배"):
    return client.get("/api/ai/similar", params={"category": category, "date": day}).json()


def test_finds_earlier_records_for_the_same_category_and_direction(client):
    review(client, "2026-01-21", reasons=["bulk"], memo="회사 행사 주문")
    body = similar(client)
    assert body["direction"] == "high"
    assert [(i["date"], i["labels"]) for i in body["items"]] == [("2026-01-21", ["단체 구매"])]
    assert "단체 구매" in body["items"][0]["text"] and "1월 21일" in body["items"][0]["text"]


def test_wording_never_claims_the_same_cause(client):
    review(client, "2026-01-21", reasons=["bulk"])
    text = similar(client)["items"][0]["text"]
    assert "같은지 확인" in text
    for banned in ("때문", "원인", "같은 이유", "확실"):
        assert banned not in text


def test_other_category_future_dates_and_generic_answers_are_excluded(client):
    review(client, "2026-01-21", reasons=["unknown"])  # '모르겠어요'만 있는 기록은 이전 기록 문구에 쓰지 않는다
    client.post("/api/anomalies/review", json={"category": "음료", "dates": ["2026-01-21"], "reasons": ["bulk"]})
    assert similar(client)["items"] == []
    review(client, TODAY.isoformat(), reasons=["promo"])
    review(client, "2026-01-21", reasons=["promo"])
    items = similar(client, "2026-01-21")["items"]  # 1/21 보다 앞선 기록은 없다 (오늘 기록은 미래라서 제외)
    assert items == []


def test_limit_is_three_newest_first(client):
    # 이전 급증일을 더 만든다: 2025년 가을 같은 요일에 급증 (평소 3번 뒤)
    base_days(client, [date(2025, 11, 5), date(2025, 11, 12), date(2025, 11, 19)])
    for day in (date(2025, 11, 26), date(2025, 12, 3), date(2025, 12, 10), date(2025, 12, 17)):
        spike(client, day)
    for day in ("2025-11-26", "2025-12-03", "2025-12-10", "2025-12-17", "2026-01-21"):
        review(client, day, reasons=["promo"])
    dates = [i["date"] for i in similar(client)["items"]]
    assert len(dates) == 3 and dates == sorted(dates, reverse=True)


def test_day_without_change_has_no_similar_items(client):
    assert similar(client, "2026-02-18")["items"] == []


def test_bad_date_is_handled(client):
    assert client.get("/api/ai/similar", params={"category": "담배", "date": "아님"}).json() == {"direction": None, "items": []}


def test_past_records_reach_the_briefing_facts(client):
    review(client, "2026-01-21", reasons=["bulk"], memo="회사 행사 주문")
    get_briefing(client)
    sent = client.app.state.ai._injected.calls[0]["user"]
    assert "단체 구매" in sent and "회사 행사 주문" in sent


# ---------------------------------------------------------------- 평가와 지표
def test_feedback_is_stored_and_counted(client):
    for helpful in (True, True, False):
        assert client.post("/api/ai/feedback", json={"kind": "briefing", "ref": "2026-02-25", "helpful": helpful}).status_code == 200
    review(client, "2026-01-21", reasons=["stock"], source="ai", raw_text="입고가 늦었어", ai_edited=True)
    review(client, "2026-01-28", reasons=["promo"])
    metrics = client.get("/api/ai/metrics").json()
    assert metrics["feedback"] == {"helpful": 2, "not_helpful": 1}
    assert metrics["notes"] == {"form": 1, "ai": 1, "ai_edited": 1}
    assert metrics["briefing"]["ai"] + metrics["briefing"]["fixed"] >= 0


@pytest.mark.parametrize("body", [{"kind": "x", "ref": "a", "helpful": True}, {"kind": "draft", "ref": "", "helpful": True}, {"kind": "draft", "ref": "가" * 81, "helpful": True}])
def test_invalid_feedback_is_rejected(client, body):
    assert client.post("/api/ai/feedback", json=body).status_code == 422


# ---------------------------------------------------------------- 보안
def test_every_ai_endpoint_requires_login(client):
    from fastapi.testclient import TestClient

    bare = TestClient(client.app)
    assert bare.get("/api/ai/status").status_code == 401
    assert bare.get("/api/ai/briefing").status_code == 401
    assert bare.get("/api/ai/similar", params={"category": "담배", "date": "2026-02-25"}).status_code == 401
    assert bare.get("/api/ai/metrics").status_code == 401
    assert bare.post("/api/ai/feedback", json={"kind": "draft", "ref": "a", "helpful": True}).status_code == 401
    assert bare.post("/api/ai/notes/draft", json={"text": "a"}).status_code == 401


def test_key_never_appears_in_responses_or_logs(tmp_path, monkeypatch, caplog):
    from app import config
    from app.ai import service as service_module
    from tests.ai_fakes import AiError

    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    monkeypatch.setattr(config, "AI_ENV_FILE", env_file)
    monkeypatch.setattr(service_module, "OpenAILLM", lambda *a, **k: FakeLLM(default=AiError("server")))
    caplog.set_level(logging.DEBUG)
    from fastapi.testclient import TestClient

    from tests.conftest import build_app
    from tests.test_home import TEST_PASSWORD

    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        seed_spike(c)
        outputs = [
            c.get("/api/ai/status").text,
            c.get("/api/ai/briefing").text,
            c.get("/api/ai/briefing").text,
            c.post("/api/ai/notes/draft", json={"text": "입고가 늦었어"}).text,
            c.get("/api/ai/metrics").text,
        ]
    assert all(SECRET not in text for text in outputs)
    assert SECRET not in caplog.text


def test_logs_do_not_contain_owner_text_or_prompts(make_client, caplog):
    caplog.set_level(logging.DEBUG)
    client = make_client(FakeLLM(default=lambda s, u: (_ for _ in ()).throw(RuntimeError("실패"))))
    seed_spike(client)
    client.post("/api/ai/notes/draft", json={"text": "점주의 아주 비밀스러운 문장"})
    get_briefing(client)
    assert "비밀스러운" not in caplog.text
