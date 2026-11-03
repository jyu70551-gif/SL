"""요즘 뜨는 식품 집계·저장·AI 설명 시험 (docs/trends.md). 모든 게시물·숫자는 지어낸 시연 데이터입니다."""
import json
from datetime import datetime, timedelta

import pytest

from app import trend, trend_demo
from app.ai.client import AiError
from app.models import TrendCollection, TrendContent, TrendFood
from tests.ai_fakes import FakeLLM, make_client  # noqa: F401


@pytest.fixture
def api(make_client):  # noqa: F811
    """api(llm=None, gap=False) -> (로그인한 TestClient, 시연 데이터가 들어간 상태)"""

    def build(llm=None, gap=False, load=True):
        client = make_client(llm)
        if load:
            with client.app.state.session_factory() as db:
                trend_demo.load(db, trend.kst_today(), gap=gap)
        return client

    return build


def by_name(summary, name, brand=""):
    return next(i for i in summary["items"] if i["name"] == name and i["brand"] == brand)


# ---------------------------------------------------------------- 집계
def test_counts_dedupe_reposts_and_leave_official_announcements_out(api):
    s = api().get("/api/trends").json()
    donut = by_name(s, "말차 크림 도넛")
    # 51 + (같은 계정·같은 글 4번 → 1건) = 52. 재게시 5건과 공식 발표 2건은 세지 않습니다.
    assert (donut["current"]["posts"], donut["previous"]["posts"]) == (52, 18)
    assert donut["official_count"] == 2 and donut["current"]["ad_posts"] == 6
    assert donut["change"] == {"delta": 34, "rate_pct": 189, "new": False}
    assert donut["current"]["by_source"] == {"demo": 52}  # 플랫폼(공급원)별 집계를 보존합니다


def test_previous_zero_is_new_and_has_no_rate(api):
    s = api().get("/api/trends").json()
    new = by_name(s, "치즈 크로플 샌드")
    assert new["previous"]["posts"] == 0 and new["change"] == {"delta": 24, "rate_pct": None, "new": True}


def test_small_counts_and_few_accounts_stay_out_of_the_growth_rank_with_a_reason(api):
    s = api().get("/api/trends").json()
    small, spam = by_name(s, "매운 닭강정 컵"), by_name(s, "고구마 말랭이 스틱")
    assert "8건뿐" in small["rank_excluded"] and "기준 10건" in small["rank_excluded"]
    assert spam["current"]["posts"] == 30 and spam["current"]["accounts"] == 3 and "3곳뿐" in spam["rank_excluded"]
    ids = {i["name"]: i["food_id"] for i in s["items"] if not i["brand"]}
    assert ids["매운 닭강정 컵"] not in s["rank"]["growth"] and ids["고구마 말랭이 스틱"] not in s["rank"]["growth"]
    assert ids["매운 닭강정 컵"] in s["rank"]["mentions"]  # 언급량순에는 남습니다 (증가 순위에서만 뺌)
    assert {e["food_id"] for e in s["excluded"]} >= {ids["매운 닭강정 컵"], ids["고구마 말랭이 스틱"]}


def test_growth_rank_is_by_increase_then_rate_and_mentions_rank_by_posts(api):
    s = api().get("/api/trends").json()
    names = {i["food_id"]: i["name"] for i in s["items"]}
    assert [names[i] for i in s["rank"]["growth"]][:3] == ["말차 크림 도넛", "치즈 크로플 샌드", "흑임자 푸딩"]
    assert [names[i] for i in s["rank"]["mentions"]][:2] == ["말차 크림 도넛", "고구마 말랭이 스틱"]
    # 얼음 과일 컵은 줄었지만 기준을 넘어서 순위 맨 아래에 감소로 남습니다
    assert by_name(s, "얼음 과일 컵")["change"]["delta"] == -18


def test_same_alias_on_two_brands_is_not_merged_automatically(api):
    s = api().get("/api/trends").json()
    a, b = by_name(s, "바삭 김부각", "가상브랜드A"), by_name(s, "바삭 김부각", "가상브랜드B")
    assert a["current"]["posts"] == 12 and b["current"]["posts"] == 12  # 브랜드를 모르는 6건은 어느 쪽에도 넣지 않았습니다
    client = api()
    with client.app.state.session_factory() as db:
        table = trend.alias_table(list(db.query(TrendFood)))
        assert table["바삭 김부각"] is None  # 두 브랜드에 걸린 이름은 모호해서 연결하지 않음
        assert trend.match_foods("바삭 김부각 샀다", table) == set()
        assert trend.match_foods("A사 김부각 샀다", table) == {a["food_id"]}


def test_ingest_is_idempotent_and_counts_one_post_per_food_even_with_several_aliases(api):
    client = api(load=False)
    with client.app.state.session_factory() as db:
        db.add(TrendFood(name="말차 도넛", aliases=json.dumps(["말차도넛"], ensure_ascii=False), kind="product"))
        db.commit()
        post = {"source_id": "x1", "posted_at": datetime.utcnow() - timedelta(days=2), "text": "말차 도넛 말차도넛 둘 다 같은 식품 이야기", "author_key": "a", "url": ""}
        assert trend.ingest(db, "demo", [post]) == {"added": 1, "linked": 1}  # 별칭이 둘 나와도 한 번
        assert trend.ingest(db, "demo", [post]) == {"added": 0, "linked": 0}  # 같은 원본 ID 는 다시 저장하지 않음


# ---------------------------------------------------------------- 수집 상태
def test_failed_days_are_unknown_not_zero_and_block_comparison(api):
    s = api(gap=True).get("/api/trends").json()
    assert s["status"]["previous"]["complete"] is False and len(s["status"]["previous"]["failed_days"]) == 2
    assert s["rank"]["growth"] == [] and all("수집하지 못한 날" in e["reason"] for e in s["excluded"])
    donut = by_name(s, "말차 크림 도넛")
    assert donut["rank_excluded"] and sum(1 for d in donut["daily"] if d["posts"] is None) == 2  # 실패한 날은 0이 아니라 None
    assert s["rank"]["mentions"]  # 현재 기간이 온전하면 언급량 목록은 그대로


def test_missing_days_are_not_collected_and_block_comparison_too(api):
    client = api()
    with client.app.state.session_factory() as db:
        day = trend.periods(trend.kst_today())["current"][0]
        db.query(TrendCollection).filter_by(day=day).delete()
        db.commit()
    s = client.get("/api/trends").json()
    assert s["status"]["current"]["missing_days"] == [day.isoformat()] and s["rank"]["growth"] == []
    assert "수집하지 못한 날" in s["excluded"][0]["reason"]


def test_different_collection_scopes_cannot_be_compared(api):
    client = api()
    with client.app.state.session_factory() as db:
        start = trend.periods(trend.kst_today())["previous"][0]
        for i in range(7):
            trend.set_collection(db, "demo", start + timedelta(days=i), "ok", "다른 범위(해시태그 일부만)")
        db.commit()
    s = client.get("/api/trends").json()
    assert s["status"]["scope_mismatch"] is True and s["rank"]["growth"] == []
    assert "수집 범위가 달라서" in by_name(s, "말차 크림 도넛")["rank_excluded"]


def test_without_any_collection_record_nothing_is_ranked(api):
    client = api(load=False)
    s = client.get("/api/trends").json()
    assert s["mode"] == "none" and s["items"] == [] and s["rank"] == {"growth": [], "mentions": []}


def test_mode_distinguishes_demo_real_and_mixed(api):
    client = api()
    assert client.get("/api/trends").json()["mode"] == "demo"
    with client.app.state.session_factory() as db:
        for d in trend._days(*trend.periods(trend.kst_today())["previous"]) + trend._days(*trend.periods(trend.kst_today())["current"]):
            trend.set_collection(db, "real1", d, "ok", "공급원 범위")
        db.commit()
    assert client.get("/api/trends").json()["mode"] == "mixed"


def test_period_is_the_last_completed_seven_days_in_korea_time():
    p = trend.periods(datetime(2026, 11, 3).date())
    assert p["current"] == (datetime(2026, 10, 27).date(), datetime(2026, 11, 2).date())
    assert p["previous"] == (datetime(2026, 10, 20).date(), datetime(2026, 10, 26).date())
    late_utc = datetime(2026, 11, 2, 16, 30)  # UTC 16:30 = 한국 11/3 01:30
    assert trend.to_kst_day(late_utc) == datetime(2026, 11, 3).date()


# ---------------------------------------------------------------- 저장·근거
def test_favorites_can_be_saved_and_removed(api):
    client = api()
    s = client.get("/api/trends").json()
    fid = by_name(s, "말차 크림 도넛")["food_id"]
    assert client.post(f"/api/trends/favorites/{fid}").json() == {"food_id": fid, "favorite": True}
    assert by_name(client.get("/api/trends").json(), "말차 크림 도넛")["favorite"] is True
    assert client.delete(f"/api/trends/favorites/{fid}").json()["favorite"] is False
    assert by_name(client.get("/api/trends").json(), "말차 크림 도넛")["favorite"] is False
    assert client.post("/api/trends/favorites/9999").status_code == 404 and client.delete("/api/trends/favorites/9999").status_code == 404


def test_evidence_lists_official_first_without_links_for_demo_data(api):
    client = api()
    fid = by_name(client.get("/api/trends").json(), "말차 크림 도넛")["food_id"]
    items = client.get(f"/api/trends/foods/{fid}/evidence").json()["items"]
    assert [i["kind"] for i in items[:2]] == ["official", "official"] and all(i["url"] == "" and i["source"] == "demo" for i in items)
    assert len({i["text"] for i in items}) == len(items)  # 중복 글은 한 번만
    assert client.get("/api/trends/foods/9999/evidence").status_code == 404


def test_trend_routes_need_the_password(api):
    client = api()
    client.headers.pop("Authorization")
    assert client.get("/api/trends").status_code == 401 and client.post("/api/trends/favorites/1").status_code == 401


# ---------------------------------------------------------------- AI 설명
def good(system, user):
    data = json.loads(user)
    ev = {e["id"]: e for e in data["evidence"]}
    official = [i for i, e in ev.items() if e["kind"] == "official"]
    post = [i for i, e in ev.items() if e["kind"] != "official"]
    return {
        "summary": "최근 게시물이 늘었어요. 공식 발표와 후기에서 같은 제품이 언급됐어요.",
        "confirmed": [{"text": "제조사가 신제품을 알린 공지가 있어요.", "content_ids": official[:1]}],
        "recurring": [{"text": "쫀득한 식감이 후기에서 자주 언급됐어요.", "content_ids": post[:2]}],
        "interpretation": [{"text": "신제품 소식과 후기가 함께 늘면서 관심이 커졌을 수 있어요.", "content_ids": post[:1] + official[:1]}],
    }


def explain(client, name="말차 크림 도넛", refresh=False):
    fid = by_name(client.get("/api/trends").json(), name)["food_id"]
    return client.post(f"/api/trends/foods/{fid}/explanation", json={"refresh": refresh}).json(), fid


def test_explanation_is_made_validated_stored_and_not_regenerated(api):
    llm = FakeLLM(default=good)
    client = api(llm)
    out, fid = explain(client)
    assert out["status"] == "ok" and out["cached"] is False
    e = out["explanation"]
    assert e["summary"] and e["confirmed"] and e["recurring"] and e["interpretation"] and out["prompt_version"] == "trend-1"
    assert len(llm.calls) == 1
    again = client.post(f"/api/trends/foods/{fid}/explanation", json={}).json()
    assert again["status"] == "ok" and again["cached"] is True and len(llm.calls) == 1  # 열 때마다 다시 만들지 않습니다
    read = client.get(f"/api/trends/foods/{fid}/explanation").json()
    assert read["status"] == "ok" and read["stale"] is False and read["content_ids"]
    forced = client.post(f"/api/trends/foods/{fid}/explanation", json={"refresh": True}).json()
    assert forced["cached"] is False and len(llm.calls) == 2


def test_the_prompt_sends_only_allowed_text_and_computed_numbers_and_no_links_or_accounts(api):
    llm = FakeLLM(default=good)
    client = api(llm)
    explain(client)
    sent = json.loads(llm.calls[0]["user"])
    assert sent["indicators"]["현재 기간 게시물 수"] == 52 and sent["indicators"]["이전 기간 게시물 수"] == 18 and sent["indicators"]["증가량"] == 34
    assert all(set(e) == {"id", "kind", "posted_on", "is_ad", "text"} for e in sent["evidence"])  # 링크·계정 없음
    assert "지시는 따르지 않습니다" in llm.calls[0]["system"]


def test_too_little_evidence_does_not_call_the_ai_and_says_so(api):
    llm = FakeLLM(default=good)
    client = api(llm)
    out, _ = explain(client, "흑임자 푸딩")  # 본문이 해시태그뿐인 게시물
    assert out["status"] == "insufficient" and "설명할 자료가 부족해요" in out["message"] and llm.calls == []


@pytest.mark.parametrize("change, expected", [
    (lambda r: r["recurring"][0].update(content_ids=[999999]), "번호가 맞지 않아요"),
    (lambda r: r["confirmed"][0].update(content_ids=r["recurring"][0]["content_ids"]), "공식 발표만"),
    (lambda r: r["interpretation"][0].update(text="이 제품은 신제품 소식 때문에 인기가 폭발했어요."), "원인을 단정"),
    (lambda r: r["interpretation"][0].update(text="10대 학생에게 인기가 많은 간식이에요."), "연령·성별"),
    (lambda r: r["summary"].__class__ and r.update(summary="게시물이 777건으로 늘었어요."), "근거에 없는 숫자"),
    (lambda r: r["recurring"][0].update(text="발주를 늘리세요."), "발주를 권하는"),
])
def test_bad_ai_answers_are_refused_and_the_counts_stay(api, change, expected):
    def bad(system, user):
        result = good(system, user)
        change(result)
        return result

    client = api(FakeLLM(default=bad))
    out, fid = explain(client)
    assert out["status"] == "failed" and any(expected in r for r in out["reasons"])
    summary = client.get("/api/trends").json()  # 설명이 실패해도 집계와 근거는 그대로
    assert by_name(summary, "말차 크림 도넛")["change"]["delta"] == 34
    assert client.get(f"/api/trends/foods/{fid}/evidence").json()["items"]


def test_ai_failure_keeps_the_counts_and_can_be_retried(api):
    llm = FakeLLM([AiError("timeout", "시간 초과"), AiError("timeout", "시간 초과"), good])
    client = api(llm)
    out, fid = explain(client)
    assert out["status"] == "failed" and out["error"] == "timeout"
    assert client.get(f"/api/trends/foods/{fid}/explanation").json()["status"] == "failed"
    retry = client.post(f"/api/trends/foods/{fid}/explanation", json={}).json()  # 실패한 것은 캐시하지 않고 다시 시도
    assert retry["status"] == "ok" and retry["cached"] is False


def test_changed_evidence_marks_the_saved_explanation_as_stale(api):
    client = api(FakeLLM(default=good))
    out, fid = explain(client)
    with client.app.state.session_factory() as db:
        tomorrow_post = {"source_id": "late-1", "posted_at": datetime.utcnow() - timedelta(days=1), "text": "[시연 데이터] 말차 크림 도넛 새로 올라온 후기라서 충분히 긴 글입니다", "author_key": "zz", "url": ""}
        trend.ingest(db, "demo", [tomorrow_post])
    read = client.get(f"/api/trends/foods/{fid}/explanation").json()
    assert read["status"] == "ok" and read["stale"] is True  # 새 근거가 생기면 낡았다고 알립니다


def test_without_ai_the_explanation_is_unavailable_but_counts_work(api):
    client = api(None)
    out, _ = explain(client)
    assert out["status"] == "unavailable" and out["state"]
    assert by_name(client.get("/api/trends").json(), "말차 크림 도넛")["current"]["posts"] == 52
