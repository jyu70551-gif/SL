"""Apify 호출·한도·결과 변환 시험 (docs/trends.md 9·11장). 실제 Apify 는 부르지 않고 가짜 응답만 씁니다. 게시물·계정·토큰은 모두 지어낸 값입니다.

이 파일의 도우미(item, post_item, fake, ai_with, DISCOVERY_ITEMS, good_names 등)는 test_trend_today.py 와 test_trend_discover.py 도 씁니다."""
import json
import urllib.error
from datetime import date, datetime, timedelta, timezone

import pytest

from app import trend_apify
from app.models import AppSetting
from app.trend_apify import ApifyError
from tests.ai_fakes import make_client  # noqa: F401

TOKEN = "apify_api_FAKE_TOKEN_123"
NOW = datetime(2026, 11, 3, 3, 0)  # UTC 03:00 = 한국 11월 3일 12:00
KST = timezone(timedelta(hours=9))


def kst(day: date, hour: int) -> str:
    return datetime(day.year, day.month, day.day, hour, tzinfo=KST).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def item(i, tag="말차도넛", day=date(2026, 11, 2), hour=12, caption=None, owner=None):
    return {"inputUrl": f"https://www.instagram.com/explore/tags/{tag}/", "id": str(1000 + i), "shortCode": f"SC{i}-{tag}", "url": f"https://www.instagram.com/p/SC{i}/",
            "caption": caption if caption is not None else f"오늘 먹은 말차 크림 도넛 후기 #말차크림도넛 번호{i}", "timestamp": kst(day, hour),
            "ownerUsername": f"user_{i}", "ownerId": owner or f"owner{i}", "likesCount": 5, "commentsCount": 1, "displayUrl": "https://img.example/x.jpg"}


@pytest.fixture
def db(make_client):  # noqa: F811
    client = make_client(None)
    with client.app.state.session_factory() as session:
        yield session


def fake(items, calls=None):
    def post(token, body, params):
        if calls is not None:
            calls.append((token, body, params))
        return items

    return post


def ai_with(db, llm):
    from app.ai.service import AiService

    return AiService(lambda: db, llm=llm)


def post_item(i, caption, tag="편의점신상", owner=None, hour=12):
    return item(i, tag=tag, hour=hour, caption=caption, owner=owner or f"o{i}")


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


# ---------------------------------------------------------------- 오류와 토큰
@pytest.mark.parametrize("status, code", [(401, "unauthorized"), (402, "payment"), (403, "forbidden"), (408, "timeout"), (429, "rate_limit"), (500, "http")])
def test_http_errors_become_short_codes_without_the_token(monkeypatch, status, code):
    def boom(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "bad " + TOKEN, {}, None)

    monkeypatch.setattr(trend_apify.urllib.request, "urlopen", boom)
    with pytest.raises(ApifyError) as e:
        trend_apify.apify_post(TOKEN, {"hashtags": ["a"]}, {"maxItems": 1})
    assert e.value.code == code and TOKEN not in str(e.value) and TOKEN not in e.value.hint


def test_network_and_bad_answers_become_codes(monkeypatch):
    def down(request, timeout):
        raise urllib.error.URLError("no route " + TOKEN)

    monkeypatch.setattr(trend_apify.urllib.request, "urlopen", down)
    with pytest.raises(ApifyError) as e:
        trend_apify.apify_post(TOKEN, {}, {})
    assert e.value.code == "network" and TOKEN not in str(e.value)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"not": "a list"}'

    monkeypatch.setattr(trend_apify.urllib.request, "urlopen", lambda request, timeout: Response())
    with pytest.raises(ApifyError) as e:
        trend_apify.apify_post(TOKEN, {}, {})
    assert e.value.code == "bad_response"


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


# ---------------------------------------------------------------- 한도
def test_default_limits_and_env_overrides(monkeypatch):
    assert trend_apify.limits() == {"per_hashtag": 30, "run_max_usd": 0.65, "monthly_results": 1500}
    monkeypatch.setenv("APIFY_RESULTS_PER_HASHTAG", "100")
    monkeypatch.setenv("APIFY_RUN_MAX_USD", "0.9")
    assert trend_apify.limits()["per_hashtag"] == 100 and trend_apify.limits()["run_max_usd"] == 0.9


def test_month_usage_adds_up_per_month(db):
    assert trend_apify.month_used(db, NOW) == 0
    assert trend_apify._bump_month(db, NOW, 7) == 7 and trend_apify._bump_month(db, NOW, 5) == 12
    assert trend_apify.month_used(db, NOW) == 12 and trend_apify.month_used(db, datetime(2026, 12, 1)) == 0
    assert db.get(AppSetting, "apify_results_202611").value == "12"


# ---------------------------------------------------------------- 결과 한 건을 쓸 모양으로
def test_to_content_keeps_only_the_minimum_and_hashes_the_account():
    c = trend_apify.to_content({**item(1), "caption": "가" * 300})
    assert set(c) == {"source_id", "posted_at", "text", "url", "author_key"}  # 계정 이름·이미지·좋아요는 쓰지 않음
    assert len(c["text"]) == trend_apify.CAPTION_CHARS and c["author_key"] != "owner1" and len(c["author_key"]) == 32
    assert trend_apify.to_content({**item(1), "ownerId": None})["author_key"] is None


def test_results_without_code_or_time_are_skipped():
    assert trend_apify.to_content({"error": "x"}) is None
    assert trend_apify.to_content({"shortCode": "A1"}) is None
    assert trend_apify.to_content({"shortCode": "A2", "timestamp": "not a time"}) is None
    assert trend_apify.to_content(item(1)) is not None
