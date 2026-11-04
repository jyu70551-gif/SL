"""상품 이름 후보 검증 시험 (docs/trends.md 9-6·11장). AI 는 가짜이고 게시물은 모두 지어낸 글입니다."""
import pytest

from app import trend_discover
from app.ai.guard import GuardError
from tests.ai_fakes import FakeLLM
from tests.test_trend_apify import ai_with, db, good_names, make_client  # noqa: F401


def test_a_name_needs_two_posts_and_two_accounts():
    posts = [{"id": 1, "text": "단독 신상 딸기모찌롤 후기", "author": "a"}, {"id": 2, "text": "딸기모찌롤 또 먹음", "author": "a"}, {"id": 3, "text": "딸기모찌롤", "author": "b"}]
    one_post = {"foods": [{"name": "딸기모찌롤", "aliases": [], "post_ids": [1]}]}
    one_account = {"foods": [{"name": "딸기모찌롤", "aliases": [], "post_ids": [1, 2]}]}
    enough = {"foods": [{"name": "딸기모찌롤", "aliases": ["딸기 모찌롤"], "post_ids": [1, 3]}]}
    assert trend_discover.verify(one_post, posts) == [] and trend_discover.verify(one_account, posts) == []
    got = trend_discover.verify(enough, posts)
    assert got[0]["posts"] == 2 and got[0]["accounts"] == 2 and got[0]["aliases"] == []  # 캡션에 없는 별칭은 받지 않음
    with pytest.raises(GuardError):
        trend_discover.verify({"foods": "x"}, posts)


def test_brands_generic_words_and_made_up_names_are_dropped(db):
    posts = [{"id": 1, "text": "오늘 먹은 피자설기 후기 GS25 신상", "author": "a"}, {"id": 2, "text": "피자 설기 드디어 먹어봄", "author": "b"}, {"id": 3, "text": "CU 피자설기 설빙 협업", "author": "c"},
             {"id": 4, "text": "GS25 도시락 신상 소개", "author": "d"}]
    names = {c["name"] for c in trend_discover.extract(ai_with(db, FakeLLM(default=good_names)), posts)}
    assert names == {"피자설기"}  # GS25(브랜드)·도시락(일반 이름)·황금 마카롱(캡션에 없는 이름)은 걸러짐


def test_usable_name_rules():
    assert trend_discover.usable_name("gs25 신상") is False and trend_discover.usable_name("편의점 디저트") is False and trend_discover.usable_name("피자설기") is True
    assert trend_discover.usable_name("가") is False and trend_discover.usable_name("#피자설기") is False


def test_without_ai_nothing_is_extracted(db):
    posts = [{"id": 1, "text": "피자설기", "author": "a"}, {"id": 2, "text": "피자설기", "author": "b"}]
    assert trend_discover.extract(ai_with(db, None), posts) == []
