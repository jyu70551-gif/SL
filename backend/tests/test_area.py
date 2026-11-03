"""상가정보(경쟁 편의점·업종 분포)와 SGIS 동네 인구. 응답은 모두 가짜이고 숫자와 이름은 가상입니다."""
import pytest

from app import area, suggestions
from app.official import OfficialError
from app.suggestions import _people
from tests.test_suggestions import TODAY, fake_forecast, facts_of, setup  # noqa: F401
from tests.ai_fakes import FakeLLM, make_client  # noqa: F401


def store_item(large, small):
    return {"indsLclsNm": large, "indsSclsNm": small}


def store_get(items, total=None, code="00"):
    def get(url, params):
        page = params["pageNo"]
        rows = items[(page - 1) * 2 : page * 2]  # 가짜는 한 쪽에 2개씩
        return {"header": {"resultCode": code}, "body": {"totalCount": len(items) if total is None else total, "items": rows}}
    return get


SAMPLE = [store_item("음식", "한식"), store_item("음식", "분식"), store_item("소매", "편의점"), store_item("소매", "편의점"), store_item("교육", "입시학원")]


@pytest.fixture(autouse=True)
def clear_caches():
    area._store_cache.clear()
    area._area_cache.clear()
    area._token.update(value="", expires_ms=0)


def test_store_survey_counts_groups_and_convenience_stores():
    got = area.stores_survey(store_get(SAMPLE), "k", 37.0, 126.0)
    assert got["total"] == 5 and not got["partial"] and got["convenience"] == 2
    assert got["groups"][:2] == [("음식", 2), ("소매", 2)] or got["groups"][:2] == [("소매", 2), ("음식", 2)]


def test_store_survey_marks_partial_when_there_are_more_than_pages(monkeypatch):
    monkeypatch.setattr(area, "STORE_MAX_PAGES", 1)
    got = area.stores_survey(store_get(SAMPLE, total=9), "k", 37.1, 126.0)
    assert got["partial"] and got["convenience"] == 0 and got["total"] == 9


@pytest.mark.parametrize("data", [{"header": {"resultCode": "99"}, "body": {}}, {"oops": 1}])
def test_store_survey_errors_become_official_errors(data):
    with pytest.raises(OfficialError):
        area.stores_survey(lambda url, params: data, "k", 37.2, 126.0)


# ---------------------------------------------------------------- SGIS
BANDS = {"30": 1000, "31": 1200, "32": 3000, "33": 3000, "34": 3500, "35": 5000, "36": 2800, "40": 2200, "24": 3100}


def sgis_get(calls=None, expired_once=False, newest_year=2024):
    state = {"expired": expired_once}

    def get(url, params):
        if calls is not None:
            calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("authentication.json"):
            return {"errCd": 0, "result": {"accessToken": "tok", "accessTimeout": "9999999999999"}}
        if state["expired"]:
            state["expired"] = False
            return {"errCd": -401, "errMsg": "만료"}
        if url.endswith("rgeocodewgs84.json"):
            return {"errCd": 0, "result": [{"sido_cd": "31", "sgg_cd": "150", "emdong_cd": "700", "emdong_nm": "가상동"}]}
        if url.endswith("/searchpopulation.json"):
            return {"errCd": 0, "result": [{"population": str(BANDS[params["age_type"]])}]}
        if url.endswith("/population.json"):
            if params["year"] > newest_year:
                return {"errCd": -100, "errMsg": "년도 정보를 확인해주세요"}
            return {"errCd": 0, "result": [{"tot_ppltn": "24000", "avg_age": "41.9", "employee_cnt": "8000", "tot_family": "9000", "avg_fmember_cnt": "2.1"}]}
        raise AssertionError(url)

    return get


def test_area_survey_finds_latest_year_and_bands():
    got = area.area_survey(sgis_get(), "id", "secret", 37.3, 126.8, TODAY)  # 2026 → 2025 거절 → 2024
    assert got["year"] == 2024 and got["dong"] == "가상동" and got["population"] == 24000 and got["avg_age"] == 41.9
    assert dict(got["bands"])["50대"] == 5000 and got["old"] == 3100


def test_area_survey_gets_a_new_token_once_when_expired_and_remembers_results():
    calls = []
    get = sgis_get(calls, expired_once=True)
    area.area_survey(get, "id", "secret", 37.4, 126.8, TODAY)
    assert calls.count("authentication.json") == 2  # 처음 + 만료 후 한 번
    before = len(calls)
    area.area_survey(get, "id", "secret", 37.4, 126.8, TODAY)
    assert len(calls) == before  # 같은 위치는 기억한 결과를 씁니다


def test_area_survey_fails_cleanly_when_no_year_has_statistics():
    with pytest.raises(OfficialError):
        area.area_survey(sgis_get(newest_year=2000), "id", "secret", 37.5, 126.8, TODAY)


@pytest.mark.parametrize("n, text", [(23999, "약 2만 4천 명"), (30000, "약 3만 명"), (5240, "약 5200명")])
def test_people_text_is_rounded(n, text):
    assert _people(n) == text


# ---------------------------------------------------------------- 사실로 들어가는 모습
def dispatch(store=None, sgis=None):
    def get(url, params):
        if "storeListInRadius" in url:
            return store(url, params)
        if "sgisapi" in url:
            return sgis(url, params)
        return fake_forecast(url, params)  # 날씨 예보
    return get


def test_facts_carry_competition_and_neighborhood(setup, monkeypatch):
    monkeypatch.setenv("STORE_API_KEY", "fake-store")
    monkeypatch.setenv("SGIS_ID", "fake-id")
    monkeypatch.setenv("SGIS_SECURITY_KEY", "fake-secret")
    client = setup(FakeLLM())
    client.app.state.official_get = dispatch(store_get(SAMPLE), sgis_get())
    facts = facts_of(client)
    assert "모두 5곳" in facts["stores"]["text"] and "음식 2곳" in facts["stores"]["text"]
    assert facts["stores:cvs"]["text"] == "반경 500m 안 편의점은 2곳이에요. 우리 점포도 들어 있을 수 있어요."
    assert "편의점" not in facts["places:500"]["text"]  # 편의점 수는 한 곳에서만
    text = facts["area"]["text"]
    assert "가상동" in text and "약 2만 4천 명" in text and "평균 나이는 41.9세" in text
    assert "가장 많은 연령대는 50대(23%)" in text
    home = facts["trade:home"]["text"]  # 종사자 8천 ÷ 거주 2만 4천 = 0.33 → 주거 중심
    assert "주거 손님" in home and "약 8000명" in home and "가구당 평균 2.1명" in home and "일반적인 추정" in home
    assert "trade:office" not in facts and "trade:transit" not in facts  # 가짜 카카오에 지하철역이 없음
    assert "10대는 6%" in text and "20대는 14%" in text and "65세 이상은 14%" in text and "2024년 통계" in text and "사는 사람 기준" in text and "동 단위" in text


def _dong(population, employees, avg_family=2.5):
    return {"dong": "가상동", "population": population, "employees": employees, "avg_family": avg_family}


@pytest.mark.parametrize("area_found, stations, expected, absent", [
    (_dong(20000, 25000), 0, ["trade:office"], ["trade:home", "trade:transit"]),  # 일하는 사람이 더 많음
    (_dong(20000, 12000), 0, ["trade:office"], ["trade:home"]),  # 절반이 넘음 (0.6)
    (_dong(20000, 7000), 0, ["trade:home"], ["trade:office"]),  # 0.35 → 주거
    (_dong(20000, 10000), 0, ["trade:office"], ["trade:home"]),  # 0.5는 경계: 직장인도 있는 동네
    (_dong(20000, 9000), 0, ["trade:home"], ["trade:office"]),  # 0.45
    (None, 2, ["trade:transit"], ["trade:office", "trade:home"]),  # 동네 정보 없이 역만
    (_dong(20000, None), 0, [], ["trade:office", "trade:home", "trade:transit"]),  # 종사자 수를 모르면 판단하지 않음
])
def test_trade_facts_follow_the_rules(area_found, stations, expected, absent):
    places_found = {"counts": {500: {"지하철역": stations}}}
    ids = {f["id"] for f in suggestions.trade_facts(area_found, places_found)}
    assert all(i in ids for i in expected) and not any(i in ids for i in absent)


def test_trade_texts_state_the_basis_and_the_family_size_only_when_small():
    big = suggestions.trade_facts(_dong(20000, 5000, 3.0), None)[0]["text"]
    small = suggestions.trade_facts(_dong(20000, 5000, 2.0), None)[0]["text"]
    assert "1~2인 가구" not in big and "1~2인 가구가 많은 편" in small
    assert "두 배가 넘어서" in small and "판매 자료로 확인한 것은 아니고" in small


def test_missing_keys_or_failures_are_stated_as_unknown(setup, monkeypatch):
    facts = facts_of(setup(FakeLLM()))  # 키 없음
    assert "알 수 없어요" in facts["stores"]["text"] and "알 수 없어요" in facts["area"]["text"]
    assert "stores:cvs" not in facts and "편의점 2곳" in facts["places:500"]["text"]  # 상가정보가 없으면 카카오 편의점 수를 그대로 둡니다

    monkeypatch.setenv("STORE_API_KEY", "fake-store")
    monkeypatch.setenv("SGIS_ID", "fake-id")
    monkeypatch.setenv("SGIS_SECURITY_KEY", "fake-secret")

    def down(url, params):
        raise OfficialError("network")

    client = setup(FakeLLM())
    client.app.state.official_get = down
    facts = facts_of(client)
    assert "가져오지 못했어요" in facts["stores"]["text"] and "가져오지 못했어요" in facts["area"]["text"]
