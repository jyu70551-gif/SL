"""이전 운영 경험 찾기(AI를 쓰지 않는 SQL 기능)와 접근 제한 시험."""
from datetime import date

import pytest

from tests.ai_fakes import FakeLLM, TODAY, make_client  # noqa: F401
from tests.test_home import add_day


def base_days(client, days):
    for day in days:
        add_day(client, day, {"담배": (10, 50000), "음료": (17, 30000)})


def spike(client, day, amount=200000):
    add_day(client, day, {"담배": (30, amount), "음료": (17, 30000)})


@pytest.fixture
def client(make_client):
    c = make_client(FakeLLM())
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


def test_similar_endpoint_requires_login(client):
    from fastapi.testclient import TestClient

    bare = TestClient(client.app)
    assert bare.get("/api/ai/status").status_code == 401
    assert bare.get("/api/ai/similar", params={"category": "담배", "date": "2026-02-25"}).status_code == 401
