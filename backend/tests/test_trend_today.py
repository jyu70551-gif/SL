"""'오늘 보기' 시험 (docs/trends.md 11장). 실제 Apify 는 부르지 않고, 게시물·계정·토큰은 모두 지어낸 값입니다."""
import json

import pytest

from app import trend_apify, trend_today
from app.trend_apify import ApifyError
from tests.ai_fakes import FakeLLM, make_client  # noqa: F401
from tests.test_trend_apify import DISCOVERY_ITEMS, NOW, TOKEN, ai_with, db, fake, good_names  # noqa: F401
from datetime import datetime


def test_counts_are_recounted_by_code_over_all_posts_not_taken_from_the_ai(db):
    ai = ai_with(db, FakeLLM(default=good_names))
    snap = trend_today.run(db, TOKEN, ai, fake(DISCOVERY_ITEMS), NOW)
    foods = {f["name"]: f for f in snap["items"]}
    assert set(foods) == {"피자설기", "생초코 찹쌀떡"}  # 브랜드·일반 이름·지어낸 이름은 빠짐
    assert foods["피자설기"]["posts"] == 3 and foods["피자설기"]["accounts"] == 3
    assert foods["생초코 찹쌀떡"]["posts"] == 3 and foods["생초코 찹쌀떡"]["accounts"] == 2  # 같은 계정 2건은 계정 1곳
    assert snap["received"] == 7 and snap["unique_posts"] == 7 and snap["day"] == "2026-11-03"
    ev = foods["피자설기"]["evidence"]
    assert len(ev) == 3 and all(e["url"].startswith("https://www.instagram.com/p/") and e["posted_on"] == "2026-11-02" and e["text"] for e in ev)
    assert snap["posted_range"] == ["2026-11-02", "2026-11-02"]


def test_the_same_day_does_not_call_apify_twice(db):
    ai = ai_with(db, FakeLLM(default=good_names))
    calls = []
    trend_today.run(db, TOKEN, ai, fake(DISCOVERY_ITEMS, calls), NOW)
    again = trend_today.run(db, TOKEN, ai, fake(DISCOVERY_ITEMS, calls), NOW)
    assert len(calls) == 1 and again["day"] == "2026-11-03"
    assert trend_apify.month_used(db, NOW) == 7


def test_next_day_collects_again(db):
    ai = ai_with(db, FakeLLM(default=good_names))
    calls = []
    trend_today.run(db, TOKEN, ai, fake(DISCOVERY_ITEMS, calls), NOW)
    trend_today.run(db, TOKEN, ai, fake(DISCOVERY_ITEMS, calls), datetime(2026, 11, 4, 3, 0))
    assert len(calls) == 2


def test_ai_off_blocks_before_any_paid_call(db):
    calls = []
    ai = ai_with(db, None)
    with pytest.raises(ApifyError) as e:
        trend_today.run(db, TOKEN, ai, fake(DISCOVERY_ITEMS, calls), NOW)
    assert e.value.code == "ai_unavailable" and calls == []


def test_monthly_limit_blocks_before_the_call(db, monkeypatch):
    monkeypatch.setenv("APIFY_MONTHLY_RESULTS", "50")
    calls = []
    with pytest.raises(ApifyError) as e:
        trend_today.run(db, TOKEN, ai_with(db, FakeLLM(default=good_names)), fake(DISCOVERY_ITEMS, calls), NOW)
    assert e.value.code == "monthly_limit" and calls == []


def test_apify_failure_keeps_the_previous_result_and_hides_the_token(db):
    ai = ai_with(db, FakeLLM(default=good_names))

    def boom(token, body, params):
        raise RuntimeError("secret " + token)

    with pytest.raises(ApifyError) as e:
        trend_today.run(db, TOKEN, ai, boom, NOW)
    assert e.value.code == "network" and TOKEN not in str(e.value) and trend_today.read(db) is None


def test_api_status_and_button(make_client, monkeypatch):
    client = make_client(FakeLLM(default=good_names))
    s = client.get("/api/trends/today").json()
    assert s["snapshot"] is None and s["can_collect"] is False and s["blocked"] == "no_token"
    assert client.post("/api/trends/today/collect").status_code == 503
    monkeypatch.setattr("app.trend_api.config.read_env_key", lambda name, path=None: TOKEN if name == "APIFY_TOKEN" else None)
    monkeypatch.setattr("app.trend_today.config.read_env_key", lambda name, path=None: TOKEN if name == "APIFY_TOKEN" else None)
    monkeypatch.setattr(trend_apify, "apify_post", fake(DISCOVERY_ITEMS))
    out = client.post("/api/trends/today/collect")
    assert out.status_code == 200 and len(out.json()["snapshot"]["items"]) == 2 and out.json()["can_collect"] is False and out.json()["blocked"] == "done_today"
    assert TOKEN not in out.text


def test_safety_posts_are_kept_out_of_the_ranking_and_shown_as_warnings(db):
    from tests.test_trend_apify import post_item

    items = DISCOVERY_ITEMS + [post_item(8, "GS25 피자설기 대장균군 검출로 판매 중단! 회수 조치", owner="o8"), post_item(9, "피자설기 회수 소식 환불 안내", owner="o9")]
    snap = trend_today.run(db, TOKEN, ai_with(db, FakeLLM(default=good_names)), fake(items), NOW)
    foods = {f["name"]: f for f in snap["items"]}
    assert foods["피자설기"]["posts"] == 3  # 회수 글 2건은 세지 않음
    assert snap["safety_posts"] == 2 and len(snap["warnings"]) == 2 and snap["unique_posts"] == 9
    assert snap["warnings"][0]["posted_on"] == "2026-11-02" and snap["warnings"][0]["foods"] == ["피자설기"] and snap["warnings"][0]["url"].startswith("https://www.instagram.com/p/")


def test_safety_words_ignore_spacing_and_leave_discount_talk_alone():
    assert trend_today.is_safety("판매 중단 됐어요") and trend_today.is_safety("대장균군 검출")
    assert not trend_today.is_safety("폐기 할인 득템") and not trend_today.is_safety("환불 없이 만족")


def test_excerpt_drops_emoji_and_is_short():
    text = "🚨🚨 GS25 " + "가" * 200
    out = trend_today.excerpt(text)
    assert "🚨" not in out and out.startswith("GS25") and len(out) <= trend_today.SNIPPET_CHARS


def test_a_product_named_only_in_safety_posts_is_named_in_the_warning_but_not_ranked(db):
    from tests.test_trend_apify import post_item

    recall = [post_item(10 + i, "찹쌀떡 대장균 검출 회수 소식 한정선피스타치오찹쌀떡 " + str(i), owner=f"r{i}") for i in range(3)]

    def names(system, user):
        ids = [p["id"] for p in json.loads(user)["posts"] if "한정선피스타치오찹쌀떡" in p["text"]]
        return {"foods": [{"name": "한정선피스타치오찹쌀떡", "aliases": [], "post_ids": ids}]}

    snap = trend_today.run(db, TOKEN, ai_with(db, FakeLLM(default=names)), fake(recall), NOW)
    assert snap["items"] == [] and snap["safety_posts"] == 3
    assert snap["warnings"][0]["foods"] == ["한정선피스타치오찹쌀떡"]


def test_a_listed_product_with_safety_posts_is_marked_with_their_count(db):
    from tests.test_trend_apify import post_item

    normal = [post_item(20 + i, "피자설기 후기 " + str(i), owner=f"n{i}") for i in range(2)]
    recall = [post_item(30, "피자설기 대장균 검출 회수 소식", owner="r1"), post_item(31, "피자 설기 판매 중단 안내", owner="r2")]
    other = [post_item(40 + i, "생초코 찹쌀떡 후기 " + str(i), owner=f"m{i}") for i in range(2)]
    snap = trend_today.run(db, TOKEN, ai_with(db, FakeLLM(default=good_names)), fake(normal + recall + other), NOW)
    foods = {f["name"]: f for f in snap["items"]}
    assert foods["피자설기"]["posts"] == 2 and foods["피자설기"]["safety_posts"] == 2  # 순위에는 안 세고 표시용으로만 셈
    assert foods["생초코 찹쌀떡"]["safety_posts"] == 0


def test_seven_distinct_hashtags_are_requested_in_one_run_within_the_cost_cap(db):
    calls = []
    trend_today.run(db, TOKEN, ai_with(db, FakeLLM(default=good_names)), fake(DISCOVERY_ITEMS, calls), NOW)
    body, params = calls[0][1], calls[0][2]
    assert body["hashtags"] == trend_apify.SEEDS and len(set(body["hashtags"])) == 7
    assert params["maxItems"] == 210 and params["maxTotalChargeUsd"] >= 0.55  # 7 × 30건 ≈ 0.55달러가 상한 안에 들어옴
    assert trend_today.status(db, ai_with(db, FakeLLM(default=good_names)), NOW)["max_results"] == 210


def test_a_cost_cap_lower_than_one_run_blocks_before_any_paid_call(db, monkeypatch):
    monkeypatch.setenv("APIFY_RUN_MAX_USD", "0.25")  # 점주 .env 에 옛 값이 남아 있는 경우
    original = trend_today.config.read_env_key
    monkeypatch.setattr(trend_today.config, "read_env_key", lambda name, path=None: TOKEN if name == "APIFY_TOKEN" else original(name, path))  # 토큰만 있는 것처럼
    calls = []
    ai = ai_with(db, FakeLLM(default=good_names))
    with pytest.raises(ApifyError) as e:
        trend_today.run(db, TOKEN, ai, fake(DISCOVERY_ITEMS, calls), NOW)
    assert e.value.code == "run_cap_low" and calls == [] and "APIFY_RUN_MAX_USD" in e.value.hint
    s = trend_today.status(db, ai, NOW)
    assert s["can_collect"] is False and s["blocked"] == "run_cap_low"
