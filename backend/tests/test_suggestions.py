"""AI 제안: 사실 모으기(코드), 제안 만들기(가짜 AI), 규칙 검사. 카카오·기상청은 가짜 응답만 쓰고 숫자와 이름은 모두 가상입니다."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import events, places, suggestions
from app.ai.client import AiError
from app.models import ScheduleEvent
from tests.ai_fakes import FakeLLM, make_client  # noqa: F401

TODAY = date(2026, 11, 2)  # 월요일. 빼빼로데이(11월 11일)까지 9일
NOW = datetime(2026, 11, 2, 9, 30)


def kakao_doc(name, distance):
    return {"place_name": name, "distance": str(distance)}


def fake_kakao(url, params, key):
    """반경이 클수록 많이 나오는 가짜 카카오 응답. 학교는 500m 안에 3곳."""
    code, radius = params["category_group_code"], params["radius"]
    base = {"SC4": 3, "AC5": 10, "FD6": 40, "CE7": 12, "CS2": 2}.get(code, 0)
    total = base * (2 if radius == 1000 else 1)
    docs = []
    if code == "SC4":
        docs = [kakao_doc("가상초등학교", 120), kakao_doc("가상중학교", 300), kakao_doc("가상고등학교", 450)]
        if radius == 1000:
            docs += [kakao_doc("가상대학교", 800), kakao_doc("가상초등학교2", 900), kakao_doc("가상여자고등학교", 950)]
    return {"meta": {"total_count": total}, "documents": docs[:15]}


def fake_forecast(url, params):
    rows = []
    for day, tmp, pcp in (("20261102", (4, 9, 11), "강수없음"), ("20261103", (3, 6, 9), "12.0mm")):
        for hour, t in zip((6, 12, 18), tmp):
            rows.append({"category": "TMP", "fcstDate": day, "fcstTime": f"{hour:02d}00", "fcstValue": str(t)})
        rows.append({"category": "POP", "fcstDate": day, "fcstTime": "0600", "fcstValue": "20" if pcp == "강수없음" else "80"})
        rows.append({"category": "PCP", "fcstDate": day, "fcstTime": "0600", "fcstValue": pcp})
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": rows}}}}


def good_cards(system, user):
    """사실 묶음의 번호와 숫자를 지켜서 만든 가짜 응답"""
    facts = {f["id"]: f["text"] for f in json.loads(user)["facts"]}
    event = "event:2026-11-11"
    assert event in facts
    return {"cards": [
        {"title": "빼빼로 코너 만들어 볼까요?", "body": "빼빼로데이가 9일 뒤예요. 근처에 학교가 3곳 있어서 입구 쪽에 진열해 보면 좋아요.", "fact_ids": [event, "places:500"]},
        {"title": "내일은 우산 챙겨 두세요", "body": "내일 비 소식이 있어서 계산대 옆에 우산을 놓아 보세요.", "fact_ids": ["weather:내일"]},
    ]}


@pytest.fixture
def setup(make_client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(suggestions, "_today", lambda: TODAY)
    monkeypatch.setattr(suggestions, "_now", lambda: NOW)
    monkeypatch.setenv("KAKAO_REST_API_KEY", "fake-kakao")
    monkeypatch.setenv("WEATHER_FORECAST_API_KEY", "fake-weather")
    places._cache.clear()
    suggestions._cache.clear()

    def build(llm=None, location=True, vacations=(), market_days=()):
        client = make_client(llm)
        client.app.state.kakao_get = fake_kakao
        client.app.state.official_get = fake_forecast
        body = {"city": "가상시", "dong": "가상동", "market_days": list(market_days)}
        if location:
            body.update(latitude=37.37, longitude=126.79)
        client.post("/api/settings/store", json=body)
        for start, end in vacations:
            client.post("/api/settings/vacations", json={"start_date": start, "end_date": end})
        with client.app.state.session_factory() as db:
            db.add(ScheduleEvent(kind="holiday", name="가상공휴일", start_date=date(2026, 11, 7), end_date=date(2026, 11, 7), source="official"))
            db.commit()
        return client

    return build


def facts_of(client):
    return {f["id"]: f for f in client.post("/api/suggestions", json={}).json()["facts"]}


# ---------------------------------------------------------------- 사실 모으기
def test_events_come_from_own_table_and_saved_holidays_merged_by_date(setup):
    client = setup()
    with client.app.state.session_factory() as db:
        found = events.upcoming(db, TODAY)
        names = {e["date"]: e["name"] for e in found}
        assert names[date(2026, 11, 11)] == "빼빼로데이" and names[date(2026, 11, 7)] == "가상공휴일"
        assert [e["days_until"] for e in found] == sorted(e["days_until"] for e in found)
        assert events.table_events(date(2026, 12, 20), date(2026, 12, 31))[date(2026, 12, 25)] == "크리스마스"
        db.add(ScheduleEvent(kind="holiday", name="기독탄신일", start_date=date(2026, 12, 25), end_date=date(2026, 12, 25), source="official"))
        db.commit()
        merged = {e["date"]: e["name"] for e in events.upcoming(db, date(2026, 12, 20))}
        assert merged[date(2026, 12, 25)] == "크리스마스(기독탄신일)"
        assert events.table_events(date(2026, 11, 15), date(2026, 11, 25))[date(2026, 11, 19)] == "수능"


def test_all_fact_groups_are_collected_with_plain_texts(setup):
    facts = facts_of(setup(FakeLLM(), vacations=[("2026-12-01", "2027-02-28")], market_days=[3, 8]))
    assert "11월 2일 월요일" in facts["date"]["text"] and "가을" in facts["date"]["text"]
    assert facts["event:2026-11-11"]["text"] == "빼빼로데이: 11월 11일 (9일 뒤)"
    assert "방학이 아니에요" in facts["vacation"]["text"] and "12월 1일" in facts["vacation"]["text"] and "29일 뒤예요" in facts["vacation"]["text"]
    assert "장날" in facts["market"]["text"] and "11월 3일" in facts["market"]["text"] and "내일" in facts["market"]["text"]
    assert facts["places:500"]["text"] == "점포 반경 500m 안에는 학교 3곳, 학원 10곳, 음식점 40곳, 카페 12곳, 편의점 2곳."
    assert "초등학교 1곳, 중학교 1곳, 고등학교 1곳" in facts["schools:500"]["text"]
    assert "가상초등학교(120m)" in facts["schools:near"]["text"]
    assert facts["weather:오늘"]["text"].startswith("오늘 기온은 4도에서 11도") and "비 소식은 없어요" in facts["weather:오늘"]["text"]
    assert "비가 12mm쯤" in facts["weather:내일"]["text"] and "80%" in facts["weather:내일"]["text"]


def test_unknown_things_are_stated_as_unknown_not_guessed(setup):
    facts = facts_of(setup(FakeLLM(), location=False))
    assert "알 수 없어요" in facts["vacation"]["text"] and "알 수 없어요" in facts["market"]["text"]
    assert "알 수 없어요" in facts["places"]["text"] and "알 수 없어요" in facts["weather"]["text"]


@pytest.mark.parametrize("span, expected", [
    (("2026-10-20", "2026-11-20"), ["방학 기간이에요", "18일 남았어요"]),
    (("2026-11-12", "2026-12-01"), ["방학이 아니에요", "10일 뒤예요"]),
    (("2027-01-10", "2027-02-20"), ["곧 시작하는 방학은 없어요"]),
])
def test_vacation_states(setup, span, expected):
    text = facts_of(setup(FakeLLM(), vacations=[span]))["vacation"]["text"]
    assert all(part in text for part in expected)


def test_extreme_weather_is_labeled_and_failures_do_not_break_the_facts(setup):
    client = setup(FakeLLM())

    def hot(url, params):
        data = fake_forecast(url, params)
        for item in data["response"]["body"]["items"]["item"]:
            if item["category"] == "TMP":
                item["fcstValue"] = "34"
        return data

    client.app.state.official_get = hot
    assert "무더운" in facts_of(client)["weather:오늘"]["text"]

    from app import official

    def broken(url, params):
        raise official.OfficialError("network")

    client.app.state.official_get = broken
    assert facts_of(client)["weather"]["text"] == "날씨 예보를 가져오지 못했어요."
    client.app.state.kakao_get = lambda *a: (_ for _ in ()).throw(places.AddressError("network"))
    places._cache.clear()
    assert facts_of(client)["places"]["text"] == "주변 시설 정보를 가져오지 못했어요."


# ---------------------------------------------------------------- 제안 만들기
def test_ai_unavailable_shows_facts_only(setup):
    body = setup(None).post("/api/suggestions", json={}).json()
    assert body["status"] == "unavailable" and body["state"] == "no_key" and body["cards"] == [] and body["facts"]


def test_cards_are_checked_and_carry_their_basis_facts(setup):
    llm = FakeLLM(default=good_cards)
    body = setup(llm).post("/api/suggestions", json={}).json()
    assert body["status"] == "ok" and len(body["cards"]) == 2 and not body["cached"]
    first = body["cards"][0]
    assert first["title"] == "빼빼로 코너 만들어 볼까요?"
    assert [f["id"] for f in first["facts"]] == ["event:2026-11-11", "places:500"]
    assert first["facts"][0]["text"] == "빼빼로데이: 11월 11일 (9일 뒤)"
    sent = llm.calls[0]
    assert sent["schema_name"] == "suggestions" and "매출" not in sent["user"]  # 점포 매출은 쓰지 않습니다


def test_same_facts_are_not_asked_again_unless_refreshed(setup):
    llm = FakeLLM(default=good_cards)
    client = setup(llm)
    client.post("/api/suggestions", json={})
    again = client.post("/api/suggestions", json={}).json()
    assert again["cached"] and len(llm.calls) == 1
    assert not client.post("/api/suggestions", json={"refresh": True}).json()["cached"] and len(llm.calls) == 2


def bad(**override):
    card = {"title": "빼빼로 진열", "body": "빼빼로데이가 9일 뒤예요.", "fact_ids": ["event:2026-11-11"]}
    card.update(override)
    return {"cards": [card]}


@pytest.mark.parametrize("response", [
    bad(body="빼빼로데이가 9일 뒤예요. 작년보다 30곳 더 팔렸어요."),               # 사실에 없는 숫자
    bad(fact_ids=["event:2099-01-01"]),                                             # 없는 사실 번호
    bad(fact_ids=[]),                                                               # 근거 없음
    bad(body="빼빼로데이 때문에 매출이 늘 거예요."),                                  # 매출 단정
    bad(body="빼빼로데이라서 분명 잘 나갈 거예요."),                                   # 확신 표현
    bad(body="학교가 3곳이라 매출이 크게 오를 거예요."),                               # 매출 단정
    bad(body="**진열**하세요 https://example.com"),                                  # 서식·링크
    bad(title="가" * 31),                                                           # 너무 긺
    {"cards": []},                                                                  # 카드 없음
    {"cards": [bad()["cards"][0], bad(title="빼빼로 진열 2")["cards"][0], bad(title="빼빼로 진열 3")["cards"][0], bad(title="빼빼로 진열 4")["cards"][0]]},  # 4개
])
def test_bad_answers_are_rejected_then_retried_once_then_reported(setup, response):
    llm = FakeLLM(default=response)
    body = setup(llm).post("/api/suggestions", json={}).json()
    assert body["status"] == "failed" and body["error"] == "guard" and body["cards"] == []
    assert len(llm.calls) == 2 and "거절됐습니다" in llm.calls[1]["system"]  # 이유를 알려 주고 한 번만 다시 시킴
    assert body["facts"]  # 실패해도 사실은 보여 줍니다


def test_natural_reasons_such_as_market_day_or_weather_are_allowed(setup):
    """"장날이라 ~", "비 소식 때문에 ~"는 이유를 말하는 자연스러운 표현이라 막지 않습니다."""
    ok = {"cards": [
        {"title": "장날 맞춤 진열", "body": "내일이 장날이라 오가는 손님이 많을 수 있어요. 간식을 앞에 두어 보세요.", "fact_ids": ["market"]},
        {"title": "우산 챙기기", "body": "비 소식 때문에 계산대 옆에 우산을 놓아 보세요. 방학이라 일찍 닫는 학원도 있을 수 있어요.", "fact_ids": ["weather:내일", "vacation"]},
    ]}
    body = setup(FakeLLM(default=ok)).post("/api/suggestions", json={}).json()
    assert body["status"] == "ok" and len(body["cards"]) == 2


def test_failure_reasons_are_returned_for_checking(setup):
    body = setup(FakeLLM(default=bad(body="빼빼로데이가 9일 뒤예요. 작년보다 30곳 더 팔렸어요."))).post("/api/suggestions", json={}).json()
    assert body["status"] == "failed" and any("숫자" in r for r in body["reasons"])


def test_a_bad_first_answer_is_recovered_by_the_retry(setup):
    llm = FakeLLM(responses=[bad(body="빼빼로데이가 99일 뒤예요.")], default=good_cards)
    body = setup(llm).post("/api/suggestions", json={}).json()
    assert body["status"] == "ok" and len(llm.calls) == 2


def test_ai_errors_are_reported_without_crashing(setup):
    body = setup(FakeLLM(default=AiError("timeout"))).post("/api/suggestions", json={}).json()
    assert body["status"] == "failed" and body["error"] == "timeout" and body["facts"]


def test_requires_login_and_never_leaks_keys(setup):
    client = setup(FakeLLM(default=good_cards))
    text = client.post("/api/suggestions", json={}).text
    assert "fake-kakao" not in text and "fake-weather" not in text
    assert TestClient(client.app).post("/api/suggestions", json={}).status_code == 401


# ---------------------------------------------------------------- 학생 상권, 대학
def test_student_area_fact_joins_schools_and_says_it_is_an_estimate(setup):
    facts = facts_of(setup(FakeLLM()))
    text = facts["students"]["text"]
    assert "초등학교 1곳, 중학교 1곳, 고등학교 1곳" in text and "여러 학교가 가까워서" in text
    assert "학생·수강생 손님의 영향을 받을 수 있는 상권" in text and "일반적인 추정" in text and "가상초등학교(120m)" in text
    assert "학원 10곳" in text and "오후와 저녁" in text
    assert "university" not in facts  # 500m 안에는 대학이 없음


def test_no_school_nearby_is_stated_and_no_university_fact(setup, monkeypatch):
    def empty(url, params, key):
        return {"meta": {"total_count": 0}, "documents": []}

    client = setup(FakeLLM())
    client.app.state.kakao_get = empty
    places._cache.clear()
    facts = facts_of(client)
    assert "학교가 없어서" in facts["students"]["text"] and "university" not in facts


def test_campus_buildings_count_as_one_university_and_get_a_rough_break_note(setup):
    def campus(url, params, key):
        docs = []
        if params["category_group_code"] == "SC4":
            docs = [kakao_doc("가상대학교", 200), kakao_doc("가상대학교 사범대학", 220), kakao_doc("가상대학교 제2캠퍼스", 260), kakao_doc("가상전문대학", 400)]
        return {"meta": {"total_count": len(docs)}, "documents": docs}

    client = setup(FakeLLM())
    client.app.state.kakao_get = campus
    places._cache.clear()
    facts = facts_of(client)
    assert "대학교 2곳" in facts["students"]["text"] and "가상대학교(200m)" in facts["schools:near"]["text"]
    assert "학교 2곳" in facts["places:500"]["text"]
    assert "학교마다 달라서 어림" in facts["university"]["text"]


@pytest.mark.parametrize("today, expected", [
    (date(2026, 7, 10), "보통 지금쯤 방학"),
    (date(2027, 1, 15), "보통 지금쯤 방학"),
    (date(2026, 11, 2), "49일 뒤쯤"),  # 12월 21일까지
    (date(2026, 4, 1), "81일 뒤쯤"),  # 6월 21일까지
])
def test_university_break_is_a_rough_calendar_estimate(today, expected):
    assert expected in suggestions.university_break_text(today)


def _area(schools, academies):
    return {"school_kinds": {500: {"초등학교": schools} if schools else {}}, "counts": {500: {"학원": academies}},
            "schools": [{"name": "가상초등학교", "kind": "초등학교", "distance_m": 100}] if schools else []}


@pytest.mark.parametrize("schools, academies, expected, absent", [
    (0, 5, ["학원 5곳", "학원이 모여 있어서", "오후와 저녁"], ["학교가 가까워서", "가장 가까운 학교"]),  # 학교 없이 학원가만
    (0, 4, ["학교가 없어서", "학원은 4곳"], ["영향을 받을 수 있는"]),  # 기준(5곳) 미만
    (2, 0, ["초등학교 2곳", "학교가 가까워서"], ["학원", "오후와 저녁"]),  # 학원 없이 학교만
    (3, 12, ["초등학교 3곳", "학원 12곳", "여러 학교가 가까워서", "오후와 저녁"], []),
])
def test_students_fact_uses_schools_or_academies(schools, academies, expected, absent):
    text = suggestions.student_facts(_area(schools, academies), TODAY)[0]["text"]
    assert all(part in text for part in expected) and not any(part in text for part in absent)


def test_cards_on_the_same_core_fact_are_merged_into_the_first(setup):
    def overlapping(system, user):
        return {"cards": [
            {"title": "학생 간식 진열", "body": "근처에 학교가 3곳 있어서 간식을 모아 두면 좋아요.", "fact_ids": ["students", "places:500"]},
            {"title": "방과 후 준비", "body": "근처에 학교가 3곳 있어서 저녁 재고를 살펴보면 좋아요.", "fact_ids": ["students", "schools:near"]},
            {"title": "내일은 우산 챙겨 두세요", "body": "내일 비 소식이 있어서 우산을 놓아 보세요.", "fact_ids": ["weather:내일"]},
        ]}

    body = setup(FakeLLM([overlapping])).post("/api/suggestions", json={}).json()
    assert body["status"] == "ok" and [c["title"] for c in body["cards"]] == ["학생 간식 진열", "내일은 우산 챙겨 두세요"]
