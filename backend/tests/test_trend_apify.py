"""Apify 인스타그램 수집 시험 (docs/trends.md 9장). 실제 Apify 는 부르지 않고 가짜 응답만 씁니다. 게시물·계정·토큰은 모두 지어낸 값입니다."""
import json
import sys
import urllib.error
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import trend, trend_apify, trend_discover
from app.ai.guard import GuardError
from tests.ai_fakes import FakeLLM
from app.models import AppSetting, TrendCollection, TrendContent, TrendFood, TrendMention
from app.trend_apify import ApifyError
from tests.ai_fakes import make_client  # noqa: F401

TOKEN = "apify_api_FAKE_TOKEN_123"
NOW = datetime(2026, 11, 3, 3, 0)  # UTC 03:00 = 한국 11월 3일 12:00 → 어제는 11월 2일
TODAY = date(2026, 11, 3)


def kst(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, tzinfo=trend.KST).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def item(i, tag="말차도넛", day=date(2026, 11, 2), hour=12, caption=None, owner=None):
    return {"inputUrl": f"https://www.instagram.com/explore/tags/{tag}/", "id": str(1000 + i), "shortCode": f"SC{i}-{tag}", "url": f"https://www.instagram.com/p/SC{i}/",
            "caption": caption if caption is not None else f"오늘 먹은 말차 크림 도넛 후기 #말차크림도넛 번호{i}", "timestamp": kst(day, hour),
            "ownerUsername": f"user_{i}", "ownerId": owner or f"owner{i}", "likesCount": 5, "commentsCount": 1, "displayUrl": "https://img.example/x.jpg"}


@pytest.fixture
def db(make_client):  # noqa: F811
    client = make_client(None)
    with client.app.state.session_factory() as session:
        yield session


@pytest.fixture
def donut(db):
    food = TrendFood(name="말차 크림 도넛", brand="", aliases=json.dumps(["말차도넛"], ensure_ascii=False), kind="product")
    db.add(food)
    db.commit()
    return food


def fake(items, calls=None):
    def post(token, body, params):
        if calls is not None:
            calls.append((token, body, params))
        return items

    return post


# ---------------------------------------------------------------- 계획과 한도
def test_plan_builds_hashtags_without_spaces_and_estimates_the_cost(db, donut):
    p = trend_apify.plan(db, [donut], NOW)
    assert p["tags"] == ["말차크림도넛", "말차도넛"] and p["per_hashtag"] == 30 and p["max_results"] == 60
    assert p["estimated_max_usd"] == pytest.approx(0.156) and p["run_max_usd"] == 0.25


def test_too_many_hashtags_and_monthly_limit_stop_the_run_before_calling(db, donut, monkeypatch):
    monkeypatch.setenv("APIFY_MAX_HASHTAGS", "1")
    with pytest.raises(ApifyError) as e:
        trend_apify.plan(db, [donut], NOW)
    assert e.value.code == "too_many_hashtags"
    monkeypatch.setenv("APIFY_MAX_HASHTAGS", "8")
    monkeypatch.setenv("APIFY_MONTHLY_RESULTS", "100")
    db.add(AppSetting(key="apify_results_202611", value="50"))
    db.commit()
    calls = []
    with pytest.raises(ApifyError) as e:
        trend_apify.collect(db, TOKEN, [donut], fake([], calls), NOW)
    assert e.value.code == "monthly_limit" and calls == []  # 한도를 넘으면 호출하지 않습니다
    with pytest.raises(ApifyError) as e:
        trend_apify.plan(db, [], NOW)
    assert e.value.code == "no_hashtags"


# ---------------------------------------------------------------- 저장 내용과 개인정보
def test_collect_stores_only_the_minimum_and_links_hashtag_posts_to_the_food(db, donut):
    calls = []
    items = [item(i) for i in range(5)] + [item(9, caption="가" * 500)]
    result = trend_apify.collect(db, TOKEN, [donut], fake(items, calls), NOW)
    assert result["received"] == 6 and result["added"] == 6 and result["days"] == {"2026-11-02": "ok"}
    token, body, params = calls[0]
    assert body == {"hashtags": ["말차크림도넛", "말차도넛"], "resultsType": "posts", "resultsLimit": 30} and params["maxTotalChargeUsd"] == 0.25 and params["maxItems"] == 60
    rows = list(db.scalars(select(TrendContent)))
    assert {r.source for r in rows} == {"instagram_apify"} and all(r.kind == "post" and not r.is_ad and not r.is_repost for r in rows)
    long = next(r for r in rows if r.source_id.startswith("SC9"))
    assert len(long.text) == 200  # 캡션은 앞 200자만
    columns = {c.name for c in TrendContent.__table__.columns}
    assert not ({"username", "owner", "likes", "comments", "image"} & columns)  # 계정 이름·좋아요·이미지 저장 칸이 없음
    assert all(r.author_key and len(r.author_key) == 32 and not r.author_key.startswith("owner") for r in rows)  # 계정은 해시
    assert "user_1" not in json.dumps([r.text for r in rows], ensure_ascii=False)
    assert len(list(db.scalars(select(TrendMention)))) == 5  # 해시태그가 공백 없는 '#말차크림도넛'이어도 연결됨 (긴 캡션은 식품 이름이 없어서 연결 안 됨)
    assert db.get(AppSetting, "apify_results_202611").value == "6"
    scope = db.get(TrendCollection, ("instagram_apify", date(2026, 11, 2))).scope
    assert "해시태그 2개" in scope and "최대 30건" in scope and TOKEN not in scope


def test_a_second_run_does_not_save_the_same_posts_again(db, donut):
    items = [item(i) for i in range(3)]
    trend_apify.collect(db, TOKEN, [donut], fake(items), NOW)
    again = trend_apify.collect(db, TOKEN, [donut], fake(items), NOW)
    assert again["received"] == 3 and again["added"] == 0
    assert db.get(AppSetting, "apify_results_202611").value == "6"  # 받은 건수는 청구된 것으로 보고 월 사용량에 더합니다


def test_posts_older_than_thirty_days_are_deleted(db, donut):
    old = item(1, day=date(2026, 9, 20))
    trend_apify.collect(db, TOKEN, [donut], fake([old, item(2)]), NOW)
    assert not list(db.scalars(select(TrendContent).where(TrendContent.source_id.like("SC1-%"))))
    assert list(db.scalars(select(TrendContent).where(TrendContent.source_id.like("SC2-%"))))


# ---------------------------------------------------------------- 수집 범위(상한)
def test_hitting_the_cap_marks_yesterday_as_unknown_not_zero(db, donut):
    items = [item(i, tag="말차크림도넛", hour=15 + i % 5) for i in range(3)] + [item(10 + i, tag="말차도넛", hour=15 + i % 5) for i in range(3)]
    result = trend_apify.collect(db, TOKEN, [donut], fake(items), NOW, per_hashtag=3)  # 해시태그마다 정확히 3건 = 상한
    assert result["days"] == {"2026-11-02": "capped"}  # 가장 오래된 게시물이 어제 15시 → 어제 앞부분(0~15시)을 못 본 것
    s = trend.build_summary(db, TODAY)
    assert "2026-11-02" in s["status"]["current"]["capped_days"] and s["rank"]["growth"] == []
    assert all("수집하지 못한 날" in e["reason"] for e in s["excluded"])


def test_coverage_reaches_earlier_days_only_when_every_hashtag_hit_the_cap_far_back():
    deep = [item(i, tag="a", day=date(2026, 10, 30), hour=10) for i in range(3)] + [item(10 + i, tag="b", day=date(2026, 10, 31), hour=10) for i in range(3)]
    assert trend_apify.coverage(deep, ["a", "b"], 3, TODAY) == {date(2026, 11, 2): "ok", date(2026, 11, 1): "ok"}  # b 는 10/31 10시까지만 거슬러 갔으니 10/31 은 앞부분을 못 봄 → 11/1 까지만 확인
    one_not_capped = [item(i, tag="a", day=date(2026, 10, 30)) for i in range(3)] + [item(10, tag="b")]
    assert trend_apify.coverage(one_not_capped, ["a", "b"], 3, TODAY) == {date(2026, 11, 2): "ok"}  # 상한에 안 닿은 해시태그는 어제만 확인된 것으로
    assert trend_apify.coverage([], ["a"], 3, TODAY) == {date(2026, 11, 2): "ok"}  # 결과가 없으면 어제는 0건으로 확인(상한에 안 닿음)


# ---------------------------------------------------------------- 오류와 토큰
@pytest.mark.parametrize("status, code", [(401, "unauthorized"), (402, "payment"), (403, "forbidden"), (408, "timeout"), (429, "rate_limit"), (500, "http")])
def test_http_errors_become_short_codes_without_the_token(monkeypatch, status, code):
    def boom(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "bad " + TOKEN, {}, None)

    monkeypatch.setattr(trend_apify.urllib.request, "urlopen", boom)
    with pytest.raises(ApifyError) as e:
        trend_apify.apify_post(TOKEN, {"hashtags": ["a"]}, {"maxItems": 1})
    assert e.value.code == code and TOKEN not in str(e.value) and TOKEN not in e.value.hint


def test_the_token_goes_in_the_authorization_header_never_in_the_url(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"[]"

    def capture(request, timeout):
        seen["url"], seen["headers"], seen["body"], seen["timeout"] = request.full_url, dict(request.header_items()), request.data, timeout
        return Response()

    monkeypatch.setattr(trend_apify.urllib.request, "urlopen", capture)
    assert trend_apify.apify_post(TOKEN, {"hashtags": ["a"]}, {"maxItems": 5, "maxTotalChargeUsd": 0.25}) == []
    assert TOKEN not in seen["url"] and seen["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert "maxTotalChargeUsd=0.25" in seen["url"] and "run-sync-get-dataset-items" in seen["url"] and seen["timeout"] > 280


def test_any_other_error_from_the_caller_is_reduced_to_a_code_without_the_message(db, donut):
    def leaky(token, body, params):
        raise RuntimeError("connection failed for " + token)

    with pytest.raises(ApifyError) as e:
        trend_apify.collect(db, TOKEN, [donut], leaky, NOW)
    assert e.value.code == "network" and TOKEN not in str(e.value)
    assert db.get(AppSetting, "apify_results_202611") is None  # 실패하면 월 사용량에 더하지 않음


def test_non_post_results_without_code_or_time_are_skipped(db, donut):
    junk = [{"error": "x"}, {"shortCode": "A1"}, {"shortCode": "A2", "timestamp": "not a time"}, item(1)]
    result = trend_apify.collect(db, TOKEN, [donut], fake(junk), NOW)
    assert result["received"] == 4 and result["added"] == 1


# ---------------------------------------------------------------- 실행 도구
def test_cli_dry_run_calls_nothing_and_a_real_run_needs_yes(tmp_path, monkeypatch, capsys):
    from app.db import Base, make_engine
    from tools import collect_instagram_trends as cli

    path = tmp_path / "t.db"
    engine = make_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setattr(trend_apify, "apify_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출하면 안 됩니다")))
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(path), "--food", "말차 크림 도넛=말차도넛", "--dry-run"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "#말차크림도넛" in out and "최대 약 60건" in out and "호출하지 않았어요" in out and TOKEN not in out
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(path), "--food", "말차 크림 도넛"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert "--yes" in str(e.value)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["x", "--db", str(path), "--food", "말차 크림 도넛", "--yes"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert "APIFY_TOKEN" in str(e.value)  # 토큰이 없으면 호출하지 않고 알려 줌 (값은 어디에도 나오지 않음)


# ---------------------------------------------------------------- 화면용 집계와의 연결
def test_collected_posts_show_up_as_a_real_source_in_the_summary(db, donut):
    day = date(2026, 11, 2)
    trend_apify.collect(db, TOKEN, [donut], fake([item(i, day=day) for i in range(4)]), NOW)
    s = trend.build_summary(db, TODAY)
    assert s["mode"] == "real" and s["sources"] == ["instagram_apify"]
    food = next(i for i in s["items"] if i["name"] == "말차 크림 도넛")
    assert food["current"]["posts"] == 4 and food["current"]["by_source"] == {"instagram_apify": 4}
    assert food["current"]["ad_posts"] == 0  # 이 공급원은 광고 표시를 알 수 없어서 표시하지 않습니다
    assert food["rank_excluded"]  # 수집한 날이 하루뿐이라 비교하지 않음


# ---------------------------------------------------------------- 자동 발견 (점주가 아무것도 하지 않아도 되게)
def post_item(i, caption, tag="편의점신상", owner=None, hour=12):
    return item(i, tag=tag, hour=hour, caption=caption, owner=owner or f"o{i}")


PIZZA = "피자설기"
DISCOVERY_ITEMS = [
    post_item(1, "오늘 먹은 피자설기 후기 GS25 신상"), post_item(2, "피자 설기 드디어 먹어봄 쫄깃"), post_item(3, "CU 피자설기 설빙 협업"),
    post_item(4, "GS25 도시락 신상 소개"), post_item(5, "생초코 찹쌀떡 품절 대란"), post_item(6, "생초코찹쌀떡 먹어봤어요 달달"), post_item(7, "같은 계정이 올린 생초코 찹쌀떡", owner="o5"),
]


def good_names(system, user):
    ids = {p["text"]: p["id"] for p in json.loads(user)["posts"]}
    pick = lambda *words: [i for t, i in ids.items() if any(w in t.replace(" ", "") for w in words)]  # noqa: E731
    return {"foods": [
        {"name": "피자설기", "aliases": ["피자 설기"], "post_ids": pick("피자설기")},
        {"name": "생초코 찹쌀떡", "aliases": ["생초코찹쌀떡"], "post_ids": pick("생초코찹쌀떡")},
        {"name": "GS25", "aliases": [], "post_ids": pick("GS25")},  # 브랜드: 상품이 아님
        {"name": "도시락", "aliases": [], "post_ids": pick("도시락")},  # 일반 이름
        {"name": "황금 마카롱", "aliases": [], "post_ids": [1, 2, 3]},  # 캡션에 없는 이름: 지어낸 것
    ]}


def test_discovery_registers_only_names_that_really_appear_in_enough_posts_and_accounts(db):
    ai = ai_with(db, FakeLLM(default=good_names))
    result = trend_apify.discover(db, TOKEN, ai, fake(DISCOVERY_ITEMS), NOW, per_hashtag=10)
    assert result["received"] == 7
    names = {c["name"]: c for c in result["candidates"]}
    assert set(names) == {"피자설기", "생초코 찹쌀떡"}  # 브랜드·일반 이름·지어낸 이름은 걸러짐
    assert names["피자설기"]["posts"] == 3 and names["피자설기"]["aliases"] == []  # 띄어쓰기만 다른 표기는 따로 별칭으로 두지 않습니다(찾을 때 띄어쓰기를 무시)
    assert names["생초코 찹쌀떡"]["posts"] == 3 and names["생초코 찹쌀떡"]["accounts"] == 2  # 같은 계정이 올린 2건은 계정 1곳으로
    assert result["registered"] == ["피자설기", "생초코 찹쌀떡"] and result["tracked"] == ["피자설기", "생초코 찹쌀떡"]
    assert {f.name for f in trend_apify.tracked(db)} == {"피자설기", "생초코 찹쌀떡"}


def ai_with(db, llm):
    from app.ai.service import AiService

    return AiService(lambda: db, llm=llm)


def test_a_name_needs_two_posts_and_two_accounts_to_be_registered():
    posts = [{"id": 1, "text": "단독 신상 딸기모찌롤 후기", "author": "a"}, {"id": 2, "text": "딸기모찌롤 또 먹음", "author": "a"}, {"id": 3, "text": "딸기모찌롤", "author": "b"}]
    one_post = {"foods": [{"name": "딸기모찌롤", "aliases": [], "post_ids": [1]}]}
    one_account = {"foods": [{"name": "딸기모찌롤", "aliases": [], "post_ids": [1, 2]}]}
    enough = {"foods": [{"name": "딸기모찌롤", "aliases": ["딸기 모찌롤"], "post_ids": [1, 3]}]}
    assert trend_discover.verify(one_post, posts) == [] and trend_discover.verify(one_account, posts) == []
    got = trend_discover.verify(enough, posts)
    assert got[0]["posts"] == 2 and got[0]["accounts"] == 2 and got[0]["aliases"] == []  # 캡션에 없는 별칭은 받지 않음
    with pytest.raises(GuardError):
        trend_discover.verify({"foods": "x"}, posts)
    assert trend_discover.usable_name("gs25 신상") is False and trend_discover.usable_name("편의점 디저트") is False and trend_discover.usable_name("피자설기") is True


def test_discovery_posts_are_not_counted_in_the_ranking_but_the_tracked_food_posts_are(db):
    ai = ai_with(db, FakeLLM(default=good_names))
    trend_apify.discover(db, TOKEN, ai, fake(DISCOVERY_ITEMS), NOW, per_hashtag=10)
    s = trend.build_summary(db, TODAY)
    assert s["sources"] == [] and all(i["current"]["posts"] == 0 for i in s["items"])  # 발견용 게시물은 세지 않음
    pizza = trend_apify.tracked(db)[0]
    tracked_items = [post_item(20 + i, "피자설기 새 후기 " + str(i), tag="피자설기") for i in range(3)]
    trend_apify.collect(db, TOKEN, [pizza], fake(tracked_items), NOW, per_hashtag=10)
    s = trend.build_summary(db, TODAY)
    assert s["sources"] == ["instagram_apify"] and next(i for i in s["items"] if i["name"] == "피자설기")["current"]["posts"] == 3


def test_auto_run_discovers_then_collects_for_the_tracked_foods_in_one_go(db):
    ai = ai_with(db, FakeLLM(default=good_names))
    calls = []

    def post(token, body, params):
        calls.append(body["hashtags"])
        return DISCOVERY_ITEMS if body["hashtags"] == trend_apify.SEEDS else [post_item(30 + i, "피자설기 후기 " + str(i), tag="피자설기") for i in range(3)]

    out = trend_apify.auto_run(db, TOKEN, ai, post, NOW, per_hashtag=10)
    assert calls[0] == trend_apify.SEEDS and "피자설기" in calls[1] and "생초코찹쌀떡" in calls[1]  # 먼저 발견, 그다음 추적 해시태그로 수집
    assert out["collection"]["received"] == 3 and out["collection"]["days"] == {"2026-11-02": "ok"}
    assert "(" in db.get(TrendCollection, ("instagram_apify", date(2026, 11, 2))).scope  # 추적 해시태그 집합의 지문이 수집 범위에 들어감


def test_when_the_tracked_slots_are_full_discovery_is_skipped_and_only_collection_runs(db, monkeypatch):
    monkeypatch.setenv("APIFY_MAX_HASHTAGS", "2")
    ai = ai_with(db, FakeLLM(default=good_names))
    full = TrendFood(name="말차 크림 도넛", brand="", aliases=json.dumps(["말차도넛"], ensure_ascii=False), kind="product")
    db.add(full)
    db.commit()
    trend_apify.set_tracked(db, [full])
    calls = []

    def post(token, body, params):
        calls.append(body["hashtags"])
        return []

    out = trend_apify.auto_run(db, TOKEN, ai, post, NOW, per_hashtag=5)
    assert out["discovery"]["skipped"] == "tracked_full" and calls == [["말차크림도넛", "말차도넛"]]  # 자리가 없으면 발견 호출을 하지 않음


def test_without_ai_discovery_finds_nothing_but_collection_still_runs(db):
    ai = ai_with(db, None)
    out = trend_apify.discover(db, TOKEN, ai, fake(DISCOVERY_ITEMS), NOW, per_hashtag=10)
    assert out["candidates"] == [] and out["registered"] == []
    assert trend_apify.auto_run(db, TOKEN, ai, fake([]), NOW, per_hashtag=10)["collection"] is None  # 추적할 식품이 아직 없으면 모으지 않음


def test_adding_a_food_beyond_the_hashtag_cap_leaves_the_tracked_list_unchanged(db):
    a = TrendFood(name="가나다라", brand="", aliases="[]", kind="product")
    b = TrendFood(name="마바사아", brand="", aliases="[]", kind="product")
    db.add_all([a, b])
    db.commit()
    assert [f.name for f in trend_apify.add_tracked(db, [a, b], 1)] == ["가나다라"]  # 해시태그 한도 1개: 두 번째는 못 올림
    assert [f.name for f in trend_apify.add_tracked(db, [b], 1)] == ["가나다라"]  # 목록이 자주 바뀌어 비교가 막히는 일을 피함
