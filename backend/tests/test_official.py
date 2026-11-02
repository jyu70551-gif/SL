"""공식 일정 가져오기(근처 학교의 방학): 거리·학교 연결·방학 기간 추정과 설정 화면 연결 시험.
학교 이름, 주소, 좌표, 날짜는 모두 가상입니다. 공식 서비스(공공데이터포털·NEIS)는 부르지 않고 가짜 응답만 씁니다."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import address, markets, official, schools
from tests.conftest import build_app
from tests.test_home import TEST_PASSWORD

STORE = (37.5000, 127.0000)


def place(school_id, name, lat, lon, kind="초등학교", status="운영", office="경기도교육청", address=None):
    return {"schoolId": school_id, "schoolNm": name, "schoolSe": kind, "operSttus": status, "cddcNm": office,
            "rdnmadr": address or f"가상도 가상시 {name}길 1", "latitude": str(lat), "longitude": str(lon)}


def metres_north(m):  # 위도 1도 ≈ 111.2 km
    return STORE[0] + m / 111_195


PLACES = [
    place("S1", "가까운초등학교", metres_north(120), STORE[1]),
    place("S2", "조금먼중학교", metres_north(430), STORE[1], kind="중학교"),
    place("S3", "너무먼고등학교", metres_north(900), STORE[1], kind="고등학교"),
    place("S4", "문닫은초등학교", metres_north(50), STORE[1], status="폐교"),
    place("S5", "이름이없는학교", metres_north(300), STORE[1]),
]


def event_rows(*events):
    return [{"EVENT_NM": name, "AA_YMD": day.strftime("%Y%m%d")} for name, day in events]


def span(name, start, end):
    return [(name, start + timedelta(days=i)) for i in range((end - start).days + 1)]


# ---------------------------------------------------------------- 거리와 학교 고르기
def test_distance_is_in_metres():
    assert official.distance_m(*STORE, metres_north(500), STORE[1]) == pytest.approx(500, abs=2)
    assert official.distance_m(*STORE, *STORE) == 0


def test_nearby_keeps_only_operating_schools_within_500m_closest_first():
    places = official.load_school_places(lambda url, params: {"header": {"resultCode": "00"}, "body": {"totalCount": len(PLACES), "items": {"item": PLACES}}}, "key")
    found = official.nearby(places, *STORE)
    assert [s["name"] for s in found] == ["가까운초등학교", "이름이없는학교", "조금먼중학교"]
    assert [s["distance_m"] for s in found] == sorted(s["distance_m"] for s in found)
    assert found[0]["distance_m"] == pytest.approx(120, abs=3)


def test_places_without_valid_coordinates_are_skipped_and_pages_are_followed():
    bad = [place("B1", "좌표없음", "", ""), place("B2", "바다한가운데", 10.0, 120.0)]
    pages = {1: PLACES[:2] + bad, 2: PLACES[2:]}
    calls = []

    def get(url, params):
        calls.append(params["pageNo"])
        return {"header": {"resultCode": "00"}, "body": {"totalCount": 1500, "items": {"item": pages.get(params["pageNo"], [])}}}

    result = official.load_school_places(get, "key")
    assert {p["school_id"] for p in result} == {"S1", "S2", "S3", "S4", "S5"} and calls == [1, 2]


def test_school_places_errors_are_reported_without_leaking_the_key():
    with pytest.raises(official.OfficialError) as error:
        official.load_school_places(lambda url, params: {"header": {"resultCode": "30"}, "body": None}, "secret-key-123")
    assert error.value.code == "api_error" and "secret-key-123" not in str(error.value)
    with pytest.raises(official.OfficialError) as no_key:
        official.load_school_places(lambda url, params: {}, "")
    assert no_key.value.code == "no_key"


def test_education_office_name_gives_the_neis_region_code():
    assert official.atpt_code_of("경기도교육청") == "J10"
    assert official.atpt_code_of("서울특별시교육청") == "B10"
    assert official.atpt_code_of("충청북도교육청") == "M10" and official.atpt_code_of("경상남도교육청") == "S10"
    assert official.atpt_code_of("알수없는교육청") is None
    # 지역이 합쳐진 이름은 광주(F10)와 전남(Q10)을 구분할 수 없어서 코드를 정하지 않습니다 (이전에는 "광주"만 보고 F10으로 잘못 읽었음)
    assert official.atpt_code_of("전남광주통합특별시교육청") is None
    assert official.atpt_codes_of("전남광주통합특별시교육청") == ["Q10", "F10"]  # 둘 다 찾아봄 (전남 먼저)
    assert official.atpt_codes_of("경기도교육청") == ["J10"] and official.atpt_codes_of("알수없는교육청") == []
    assert official.atpt_code_of("광주광역시교육청") == "F10" and official.atpt_code_of("전라남도교육청") == "Q10"


# ---------------------------------------------------------------- NEIS 학교 연결
def neis_info(rows):
    for r in rows:
        r.setdefault("ATPT_OFCDC_SC_CODE", "J10")
    return {"schoolInfo": [{"head": [{"list_total_count": len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]}, {"row": rows}]}


def test_neis_code_prefers_the_school_with_the_same_road_address():
    rows = [{"SD_SCHUL_CODE": "111", "ORG_RDNMA": "가상도 가상시 다른길 5"}, {"SD_SCHUL_CODE": "222", "ORG_RDNMA": "가상도  가상시 같은길 1"}]
    assert official.neis_school_code(lambda u, p: neis_info(rows), "k", "J10", "같은학교", "가상도 가상시 같은길 1") == ("J10", "222")


def test_neis_code_accepts_a_single_match_and_refuses_an_ambiguous_one():
    one = [{"SD_SCHUL_CODE": "111", "ORG_RDNMA": "주소가 조금 다름"}]
    two = one + [{"SD_SCHUL_CODE": "222", "ORG_RDNMA": "또 다른 주소"}]
    assert official.neis_school_code(lambda u, p: neis_info(one), "k", "J10", "학교", "가상도 가상시 길 1") == ("J10", "111")
    assert official.neis_school_code(lambda u, p: neis_info(two), "k", "J10", "학교", "가상도 가상시 길 1") is None
    nothing = {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
    assert official.neis_school_code(lambda u, p: nothing, "k", "J10", "학교", "가상도 가상시 길 1") is None


def test_neis_code_is_found_without_the_education_office_when_the_office_is_unknown_or_wrong():
    """교육청 이름이 합쳐졌거나 바뀌어도, 교육청을 지정하지 않고 도로명주소가 같은 학교를 찾아 그 학교의 교육청 코드를 씁니다."""
    calls = []

    def get(url, params):
        calls.append(params.get("ATPT_OFCDC_SC_CODE"))
        if params.get("ATPT_OFCDC_SC_CODE") == "F10":
            return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}  # 잘못 고른 광주 교육청에는 없음
        rows = [{"SD_SCHUL_CODE": "7140245", "ATPT_OFCDC_SC_CODE": "Q10", "ORG_RDNMA": "전남광주통합특별시 순천시 삼산로 104"},
                {"SD_SCHUL_CODE": "999", "ATPT_OFCDC_SC_CODE": "B10", "ORG_RDNMA": "서울특별시 어딘가 1"}]
        return neis_info(rows)

    address = "전남광주통합특별시 순천시 삼산로 104"
    assert official.neis_school_code(get, "k", None, "순천효산고등학교", address) == ("Q10", "7140245")  # 코드를 몰라도 찾음
    assert official.neis_school_code(get, "k", "F10", "순천효산고등학교", address) == ("Q10", "7140245")  # 잘못 골라도 다시 찾음
    assert calls == [None, "F10", None]
    # 교육청을 지정하지 않을 때는 이름만 같은 다른 지역 학교를 받아들이지 않습니다
    one_other = {"schoolInfo": [{"head": []}, {"row": [{"SD_SCHUL_CODE": "1", "ATPT_OFCDC_SC_CODE": "B10", "ORG_RDNMA": "서울특별시 어딘가 1"}]}]}
    assert official.neis_school_code(lambda u, p: one_other, "k", None, "순천효산고등학교", address) is None


def test_road_key_ignores_district_names_parentheses_and_lot_suffix():
    same = ["경기도 수원시 영통구 중부대로448번길 84", "경기도 수원시 영통구 중부대로448번길 84번지", "수원시 중부대로448번길 84 (영통동)"]
    assert {official.road_key(a) for a in same} == {("중부대로448번길", "84")}
    assert official.road_key("강원특별자치도 속초시 수복로 117") == official.road_key("강원도 속초시 수복로 117") == ("수복로", "117")
    assert official.road_key("전남광주통합특별시 해남군 현산면 현산북평로") is None  # 건물 번호가 없으면 비교하지 않음


def test_neis_code_survives_address_notation_differences_but_not_different_buildings():
    """공공데이터와 NEIS가 구 이름(만세구·원미구)이나 번지 표기를 다르게 적어도 같은 건물이면 연결합니다. (전국 점검에서 나온 실제 모양)"""
    def rows_for(*rows):
        return lambda u, p: neis_info([{"SD_SCHUL_CODE": c, "ORG_RDNMA": a, "ATPT_OFCDC_SC_CODE": "J10"} for c, a in rows])

    other = ("999", "경기도 부천시 계남로 29")
    assert official.neis_school_code(rows_for(("111", "경기도 화성시 우정읍 석천길 52"), other), "k", ["J10"], "석천초등학교", "경기도 화성시 만세구 우정읍 석천길 52") == ("J10", "111")
    assert official.neis_school_code(rows_for(("111", "경기도 부천시 부흥로 93"), other), "k", ["J10"], "상원초등학교", "경기도 부천시 원미구 부흥로 93") == ("J10", "111")
    assert official.neis_school_code(rows_for(("111", "경기도 수원시 영통구 중부대로448번길 84번지"), other), "k", ["J10"], "원일초등학교", "경기도 수원시 영통구 중부대로448번길 84") == ("J10", "111")
    # 같은 이름이 여럿이고 건물 번호가 다르면 고르지 않음 (잘못 연결하는 것보다 못 찾는 편이 안전)
    assert official.neis_school_code(rows_for(("111", "경기도 안산시 원선로 113"), other), "k", ["J10"], "원일초등학교", "경기도 수원시 영통구 중부대로448번길 84") is None
    # 같은 건물이 둘이면 구분할 수 없으니 고르지 않음 (교육청을 알 때도, 모를 때도)
    twin = rows_for(("111", "경기도 화성시 우정읍 석천길 52"), ("222", "경기도 화성시 우정읍 석천길 52번지"))
    assert official.neis_school_code(twin, "k", ["J10"], "석천초등학교", "경기도 화성시 만세구 우정읍 석천길 52") is None
    assert official.neis_school_code(twin, "k", None, "석천초등학교", "경기도 화성시 만세구 우정읍 석천길 52") is None


def test_merged_education_office_tries_jeonnam_then_gwangju():
    asked = []

    def get(url, params):
        asked.append(params.get("ATPT_OFCDC_SC_CODE"))
        if params.get("ATPT_OFCDC_SC_CODE") == "F10":
            return neis_info([{"SD_SCHUL_CODE": "555", "ATPT_OFCDC_SC_CODE": "F10", "ORG_RDNMA": "전남광주통합특별시 광산구 가상로 1"}])
        return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}

    codes = official.atpt_codes_of("전남광주통합특별시교육청")
    assert official.neis_school_code(get, "k", codes, "가상학교", "전남광주통합특별시 광산구 가상로 99") == ("F10", "555")  # 광주 쪽 학교(이름이 하나뿐)
    assert asked == ["Q10", "F10"]


def test_neis_error_codes_raise_instead_of_pretending_there_is_no_data():
    with pytest.raises(official.OfficialError):
        official.neis_school_code(lambda u, p: {"RESULT": {"CODE": "ERROR-290", "MESSAGE": "인증키가 유효하지 않습니다."}}, "k", "J10", "학교", "주소")


# ---------------------------------------------------------------- 방학 기간 추정
def test_daily_vacation_rows_become_one_period_per_vacation():
    rows = event_rows(
        ("여름방학식", date(2026, 7, 27)), *span("여름방학", date(2026, 7, 28), date(2026, 8, 19)), ("개학식", date(2026, 8, 20)),
        ("토요휴업일", date(2026, 8, 1)), *span("겨울방학", date(2027, 1, 6), date(2027, 2, 28)),
    )
    assert official.vacation_periods(rows) == [
        {"label": "여름방학", "start_date": "2026-07-28", "end_date": "2026-08-19", "days": 23},
        {"label": "겨울방학", "start_date": "2027-01-06", "end_date": "2027-02-28", "days": 54},
    ]


def test_weekday_only_rows_are_joined_across_weekends_but_not_across_school_days():
    # 2026-07-27(월) ~ 07-31(금), 08-03(월) ~ 08-07(금): 주말만 비어 있으므로 한 기간
    weekdays = [("여름방학", date(2026, 7, 27) + timedelta(days=i)) for i in list(range(5)) + list(range(7, 12))]
    assert [(p["start_date"], p["end_date"]) for p in official.vacation_periods(event_rows(*weekdays))] == [("2026-07-27", "2026-08-07")]
    broken = event_rows(("여름방학", date(2026, 7, 27)), ("여름방학", date(2026, 7, 30)))  # 사이에 평일이 있으면 따로
    assert len(official.vacation_periods(broken)) == 2


def test_only_start_and_end_ceremonies_give_the_days_in_between():
    rows = event_rows(("방학식(여름)", date(2026, 7, 21)), ("개학식", date(2026, 8, 18)), ("겨울방학식", date(2026, 12, 24)), ("개학식", date(2027, 3, 2)))
    assert official.vacation_periods(rows) == [
        {"label": "여름방학", "start_date": "2026-07-22", "end_date": "2026-08-17", "days": 27},
        {"label": "겨울방학", "start_date": "2026-12-25", "end_date": "2027-03-01", "days": 67},
    ]


def test_ceremony_rows_are_not_vacation_days_and_unrelated_events_are_ignored():
    unrelated = event_rows(("토요휴업일", date(2026, 8, 1)), ("학교장재량휴업일", date(2026, 5, 4)), ("체육대회", date(2026, 5, 20)))
    assert official.vacation_periods(unrelated) == []  # 방학과 상관없는 일정은 무시
    only_start = event_rows(("여름방학식", date(2026, 7, 27)))  # 개학식이 없으면 끝을 알 수 없으므로 추정하지 않는다 → 점주 입력
    assert official.vacation_periods(only_start) == []
    next_day = event_rows(("여름방학식", date(2026, 7, 27)), ("개학식", date(2026, 7, 28)))  # 방학식 바로 다음 날이 개학식이면 방학이 아니다
    assert official.vacation_periods(next_day) == []
    # 방학식·개학식 행은 방학 '날'로 세지 않는다: 날마다 적힌 방학이 있으면 그 날들만 기간이 된다
    both = event_rows(("여름방학식", date(2026, 7, 27)), *span("여름방학", date(2026, 7, 28), date(2026, 8, 19)), ("개학식", date(2026, 8, 20)))
    assert [(p["start_date"], p["end_date"]) for p in official.vacation_periods(both)] == [("2026-07-28", "2026-08-19")]

def test_rows_with_unreadable_dates_are_skipped():
    rows = [{"EVENT_NM": "여름방학", "AA_YMD": "날짜아님"}, {"EVENT_NM": "여름방학", "AA_YMD": "20260728"}]
    assert official.vacation_periods(rows)[0]["days"] == 1


# ---------------------------------------------------------------- 설정 화면 연결
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    monkeypatch.setenv("DATA_GO_KR_API_KEY", "fake-data-key")
    monkeypatch.setenv("NEIS_API_KEY", "fake-neis-key")
    schools._places_cache.update(at=0.0, places=[])
    calls = {"get": []}

    def fake_get(url, params):
        calls["get"].append(url)
        if url == official.SCHOOL_PLACE_URL:
            return {"header": {"resultCode": "00"}, "body": {"totalCount": len(PLACES), "items": {"item": PLACES}}}
        if url == official.NEIS_SCHOOL_INFO_URL:
            if params["SCHUL_NM"] == "이름이없는학교":
                return {"RESULT": {"CODE": "INFO-200"}}
            return neis_info([{"SD_SCHUL_CODE": "CODE-" + params["SCHUL_NM"], "ORG_RDNMA": f"가상도 가상시 {params['SCHUL_NM']}길 1"}])
        if url == official.NEIS_SCHEDULE_URL:
            if params["SD_SCHUL_CODE"] == "CODE-조금먼중학교":
                return {"RESULT": {"CODE": "INFO-200"}}  # 일정이 없는 학교
            rows = event_rows(*span("여름방학", date(2026, 7, 28), date(2026, 8, 19)), *span("겨울방학", date(2027, 1, 6), date(2027, 2, 28)))
            return {"SchoolSchedule": [{"head": [{"list_total_count": len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]}, {"row": rows}]}
        raise AssertionError(url)

    app = build_app(tmp_path)
    app.state.official_get = fake_get
    with TestClient(app) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        c.calls = calls
        yield c


def set_store(client, lat=STORE[0], lon=STORE[1]):
    return client.post("/api/settings/store", json={"city": "가상시", "dong": "가상동", "latitude": lat, "longitude": lon})


def test_store_location_is_saved_cleared_and_validated(client):
    assert client.get("/api/settings/store").json()["latitude"] is None
    saved = set_store(client).json()
    assert (saved["latitude"], saved["longitude"]) == STORE and client.get("/api/settings/store").json()["latitude"] == STORE[0]
    for bad in ({"latitude": 37.5}, {"longitude": 127.0}, {"latitude": 60.0, "longitude": 127.0}, {"latitude": 37.5, "longitude": 10.0}):
        assert client.post("/api/settings/store", json=bad).status_code == 422
    assert client.get("/api/settings/store").json()["latitude"] == STORE[0]  # 잘못된 값은 저장되지 않는다
    cleared = client.post("/api/settings/store", json={"city": "가상시"}).json()
    assert cleared["latitude"] is None and cleared["longitude"] is None


def test_school_addresses_need_the_password(client):
    client.headers.pop("Authorization")
    assert client.get("/api/settings/schools").status_code == 401
    assert client.post("/api/settings/schools/vacations", json={"school_ids": ["S1"]}).status_code == 401
    assert client.post("/api/settings/schools/vacations/save", json={"items": []}).status_code == 401


def test_nearby_schools_say_what_is_missing_before_calling_anything(client, monkeypatch):
    assert client.get("/api/settings/schools").json()["status"] == "no_location"
    set_store(client)
    monkeypatch.delenv("DATA_GO_KR_API_KEY")
    assert client.get("/api/settings/schools").json()["status"] == "no_key"
    assert client.calls["get"] == []  # 위치나 키가 없으면 공식 서비스를 부르지 않는다


def test_nearby_schools_lists_schools_within_500m_and_caches_the_national_list(client):
    set_store(client)
    first = client.get("/api/settings/schools").json()
    assert first["status"] == "ready" and first["radius_m"] == 500
    assert [s["name"] for s in first["items"]] == ["가까운초등학교", "이름이없는학교", "조금먼중학교"]
    client.get("/api/settings/schools")
    assert client.calls["get"].count(official.SCHOOL_PLACE_URL) == 1  # 전국 학교 목록은 하루 한 번만 받는다


def test_upstream_failure_is_reported_as_unavailable(client):
    set_store(client)

    def broken(url, params):
        raise official.OfficialError("network")

    client.app.state.official_get = broken
    response = client.get("/api/settings/schools")
    assert response.status_code == 502 and response.json()["detail"] == {"code": "source_unavailable", "reason": "network"}


def test_preview_proposes_periods_per_school_and_saves_nothing(client):
    set_store(client)
    client.get("/api/settings/schools")
    preview = client.post("/api/settings/schools/vacations", json={"school_ids": ["S1", "S2", "S5"]}).json()
    by_name = {s["name"]: s for s in preview["schools"]}
    assert preview["status"] == "ready"
    assert [(p["label"], p["start_date"], p["end_date"]) for p in by_name["가까운초등학교"]["periods"]] == [("여름방학", "2026-07-28", "2026-08-19"), ("겨울방학", "2027-01-06", "2027-02-28")]
    assert by_name["조금먼중학교"]["status"] == "none_found"  # 일정이 없으면 직접 입력 안내
    assert by_name["이름이없는학교"]["status"] == "no_code"  # NEIS에서 찾지 못하면 직접 입력 안내
    assert client.get("/api/settings/vacations").json()["items"] == []  # 미리보기는 저장하지 않는다


def test_only_the_items_the_owner_confirms_are_saved_with_the_official_source(client):
    set_store(client)
    client.get("/api/settings/schools")
    first = client.post("/api/settings/schools/vacations/save", json={"items": [{"school_id": "S1", "label": "여름방학", "start_date": "2026-07-28", "end_date": "2026-08-19"}]}).json()
    assert first["saved"] == 1
    assert [(i["name"], i["source"], i["start_date"]) for i in first["items"]] == [("가까운초등학교 여름방학", "official", "2026-07-28")]
    again = client.post("/api/settings/schools/vacations/save", json={"items": [{"school_id": "S1", "label": "여름방학", "start_date": "2026-07-28", "end_date": "2026-08-19"}]}).json()
    assert again["saved"] == 0 and len(again["items"]) == 1  # 같은 일정을 두 번 저장하지 않는다
    preview = client.post("/api/settings/schools/vacations", json={"school_ids": ["S1"]}).json()
    assert [p["already_saved"] for p in preview["schools"][0]["periods"]] == [True, False]  # 이미 저장한 것은 표시


def test_saved_official_vacations_join_the_owner_ones_and_the_merged_list(client):
    from app.settings import merged_vacations

    set_store(client)
    client.get("/api/settings/schools")
    client.post("/api/settings/vacations", json={"start_date": "2026-08-15", "end_date": "2026-08-31"})
    client.post("/api/settings/schools/vacations/save", json={"items": [{"school_id": "S1", "label": "여름방학", "start_date": "2026-07-28", "end_date": "2026-08-19"}]})
    items = client.get("/api/settings/vacations").json()["items"]
    assert {i["source"] for i in items} == {"owner", "official"}
    with client.app.state.session_factory() as db:
        assert merged_vacations(db) == [(date(2026, 7, 28), date(2026, 8, 31))]


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"items": []}, 422),
        ({"items": [{"school_id": "없는학교", "label": "여름방학", "start_date": "2026-07-28", "end_date": "2026-08-19"}]}, 404),
        ({"items": [{"school_id": "S1", "label": "여름방학", "start_date": "2026-08-19", "end_date": "2026-07-28"}]}, 422),
        ({"items": [{"school_id": "S1", "label": "여름방학", "start_date": "엉터리", "end_date": "2026-07-28"}]}, 422),
    ],
)
def test_bad_save_requests_store_nothing(client, payload, status):
    set_store(client)
    client.get("/api/settings/schools")
    assert client.post("/api/settings/schools/vacations/save", json=payload).status_code == status
    assert client.get("/api/settings/vacations").json()["items"] == []


def test_preview_rejects_empty_or_too_many_schools_and_unknown_ids(client):
    set_store(client)
    client.get("/api/settings/schools")
    assert client.post("/api/settings/schools/vacations", json={"school_ids": []}).status_code == 422
    assert client.post("/api/settings/schools/vacations", json={"school_ids": [f"S{i}" for i in range(11)]}).status_code == 422
    assert client.post("/api/settings/schools/vacations", json={"school_ids": ["없는학교"]}).status_code == 404


def test_preview_without_a_neis_key_asks_for_it(client, monkeypatch):
    set_store(client)
    client.get("/api/settings/schools")
    monkeypatch.delenv("NEIS_API_KEY")
    assert client.post("/api/settings/schools/vacations", json={"school_ids": ["S1"]}).json() == {"status": "no_key", "schools": []}


def test_a_school_that_fails_does_not_hide_the_others(client):
    set_store(client)
    client.get("/api/settings/schools")
    original = client.app.state.official_get

    def flaky(url, params):
        if url == official.NEIS_SCHEDULE_URL and params["SD_SCHUL_CODE"] == "CODE-가까운초등학교":
            raise official.OfficialError("network")
        return original(url, params)

    client.app.state.official_get = flaky
    result = client.post("/api/settings/schools/vacations", json={"school_ids": ["S1", "S5", "S2"]}).json()["schools"]
    assert {s["name"]: s["status"] for s in result} == {"가까운초등학교": "unavailable", "이름이없는학교": "no_code", "조금먼중학교": "none_found"}


# ---------------------------------------------------------------- 점포 주소 검색 (카카오, 가짜 응답)
KAKAO_DOCS = {"documents": [
    {"address_name": "가상도 가상시 가상동 1", "x": "127.0001", "y": "37.5001",
     "address": {"region_2depth_name": "가상시", "region_3depth_name": "가상동"},
     "road_address": {"address_name": "가상도 가상시 가상로 12"}},
    {"address_name": "가상도 가상시 바다동", "x": "120.0", "y": "10.0", "address": {"region_2depth_name": "가상시", "region_3depth_name": "바다동"}},
    {"address_name": "좌표없음", "address": {}},
]}


def test_address_search_returns_candidates_and_skips_bad_ones(client, monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "fake-kakao-key")
    seen = {}

    def fake(url, params, key):
        seen.update(params=params, key=key)
        return KAKAO_DOCS

    client.app.state.kakao_get = fake
    body = client.get("/api/settings/store/address", params={"q": "가상로 12"}).json()
    assert body == {"status": "ready", "items": [
        {"label": "가상도 가상시 가상로 12", "city": "가상시", "dong": "가상동", "latitude": 37.5001, "longitude": 127.0001}]}
    assert seen["params"]["query"] == "가상로 12" and seen["key"] == "fake-kakao-key"


def test_address_search_without_key_or_short_query_does_not_call_kakao(client, monkeypatch):
    client.app.state.kakao_get = lambda *a: pytest.fail("호출하면 안 됩니다")
    assert client.get("/api/settings/store/address", params={"q": "가"}).json() == {"status": "ready", "items": []}
    assert client.get("/api/settings/store/address", params={"q": "가상로 12"}).json() == {"status": "no_key", "items": []}


def test_address_search_failure_is_502_and_requires_login(client, monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "fake-kakao-key")

    def broken(url, params, key):
        raise address.AddressError("rejected")

    client.app.state.kakao_get = broken
    response = client.get("/api/settings/store/address", params={"q": "가상로 12"})
    assert response.status_code == 502 and response.json()["detail"] == {"code": "address_unavailable", "reason": "rejected"}
    assert "fake-kakao-key" not in response.text
    client.headers.pop("Authorization")
    assert client.get("/api/settings/store/address", params={"q": "가상로 12"}).status_code == 401


# ---------------------------------------------------------------- 근처 장날 (전통시장, 가짜 응답)
def market(name, lat, lon, cycle, address=None):
    return {"mrktNm": name, "mrktEstblCycle": cycle, "rdnmadr": address or f"가상도 가상시 {name}길 1",
            "latitude": str(lat), "longitude": str(lon)}


MARKETS = [
    market("가까운오일장", metres_north(200), STORE[1], "3일+8일"),
    market("가까운상설시장", metres_north(100), STORE[1], "매일"),
    market("끝자리오일장", metres_north(300), STORE[1], "5일+10일"),
    market("이상한주기시장", metres_north(350), STORE[1], "2일+4일+7일+9일"),
    market("먼오일장", metres_north(900), STORE[1], "1일+6일"),
    market("좌표없는시장", "", "", "2일+7일"),
]


@pytest.fixture
def market_client(client, monkeypatch):
    monkeypatch.setenv("MARKET_API_KEY", "fake-market-key")
    markets._places_cache.update(at=0.0, places=[])
    client.app.state.official_get = lambda url, params: {
        "header": {"resultCode": "00"}, "body": {"totalCount": len(MARKETS), "items": {"item": MARKETS}}}
    return client


def test_cycle_text_becomes_market_days():
    assert official.market_days_from_cycle("3일+8일") == [3, 8, 13, 18, 23, 28]
    assert official.market_days_from_cycle("5일+10일") == [5, 10, 15, 20, 25, 30]
    assert official.market_days_from_cycle("1일+6일") == [1, 6, 11, 16, 21, 26, 31]
    for odd in ["상설", "매일", "", "2일+4일+7일+9일", "2일+5일", "6일+11일"]:
        assert official.market_days_from_cycle(odd) is None


def test_markets_need_location_and_key(client, monkeypatch):
    assert client.get("/api/settings/markets").json()["status"] == "no_location"
    set_store(client)
    assert client.get("/api/settings/markets").json()["status"] == "no_key"


def test_nearby_markets_are_sorted_and_classified(market_client):
    set_store(market_client)
    body = market_client.get("/api/settings/markets").json()
    assert body["status"] == "ready" and body["saved_days"] == []
    assert [(m["name"], m["kind"]) for m in body["items"]] == [
        ("가까운상설시장", "permanent"), ("가까운오일장", "periodic"), ("끝자리오일장", "periodic"), ("이상한주기시장", "unknown")]
    assert body["items"][1]["days"] == [3, 8, 13, 18, 23, 28]


def test_saving_markets_replaces_market_days_and_empty_clears(market_client):
    set_store(market_client)
    items = {m["name"]: m["market_id"] for m in market_client.get("/api/settings/markets").json()["items"]}
    saved = market_client.post("/api/settings/markets/save", json={"market_ids": [items["가까운오일장"]]}).json()
    assert saved["saved_days"] == [3, 8, 13, 18, 23, 28]
    assert market_client.get("/api/settings/store").json()["market_days"] == saved["saved_days"]
    both = market_client.post("/api/settings/markets/save", json={"market_ids": [items["가까운오일장"], items["끝자리오일장"]]}).json()
    assert both["saved_days"] == sorted(set(range(1, 32)) & {d for d in range(1, 32) if d % 5 in (3, 0)})
    assert market_client.post("/api/settings/markets/save", json={"market_ids": []}).json() == {"saved_days": []}


def test_saving_rejects_permanent_unknown_and_far_markets_without_changing_days(market_client):
    set_store(market_client)
    items = {m["name"]: m["market_id"] for m in market_client.get("/api/settings/markets").json()["items"]}
    market_client.post("/api/settings/markets/save", json={"market_ids": [items["가까운오일장"]]})
    for bad, status in [(items["가까운상설시장"], 422), (items["이상한주기시장"], 422), ("먼오일장|가상도 가상시 먼오일장길 1", 404), ("없는시장|x", 404)]:
        assert market_client.post("/api/settings/markets/save", json={"market_ids": [bad]}).status_code == status
    assert market_client.get("/api/settings/store").json()["market_days"] == [3, 8, 13, 18, 23, 28]


def test_markets_require_login_and_hide_key_on_failure(market_client):
    set_store(market_client)

    def broken(url, params):
        raise official.OfficialError("network")

    market_client.app.state.official_get = broken
    response = market_client.get("/api/settings/markets")
    assert response.status_code == 502 and "fake-market-key" not in response.text
    market_client.headers.pop("Authorization")
    assert market_client.get("/api/settings/markets").status_code == 401


# ---------------------------------------------------------------- 공휴일 (한국천문연구원 특일 정보, 가짜 응답)
def holiday_response(year, *rows):
    items = [{"locdate": d.strftime("%Y%m%d"), "dateName": name, "isHoliday": flag} for d, name, flag in rows]
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items} if items else "", "totalCount": len(items)}}}


@pytest.fixture
def holiday_client(client, monkeypatch):
    monkeypatch.setenv("HOLIDAY_API_KEY", "fake-holiday-key")
    this_year = date.today().year

    def fake(url, params):
        y = params["solYear"]
        rows = {this_year: [(date(y, 1, 1), "1월1일", "Y"), (date(y, 5, 1), "근로자의날", "N"), (date(y, 3, 2), "대체공휴일(삼일절)", "Y")],
                this_year + 1: [(date(y, 1, 1), "1월1일", "Y")]}.get(y, [])
        return holiday_response(y, *rows)

    client.app.state.official_get = fake
    client.this_year = this_year
    return client


def test_fetch_holidays_keeps_only_days_off_and_handles_empty_year():
    key_rows = holiday_response(2030, (date(2030, 5, 1), "근로자의날", "N"), (date(2030, 1, 1), "1월1일", "Y"), (date(2030, 3, 2), "대체공휴일(삼일절)", "Y"))
    got = official.fetch_holidays(lambda u, p: key_rows, "k", 2030)
    assert [(h["date"], h["name"]) for h in got] == [(date(2030, 1, 1), "1월1일"), (date(2030, 3, 2), "대체공휴일(삼일절)")]
    assert official.fetch_holidays(lambda u, p: holiday_response(2031), "k", 2031) == []
    with pytest.raises(official.OfficialError):
        official.fetch_holidays(lambda u, p: {"response": {"header": {"resultCode": "30"}}}, "k", 2030)


def test_holidays_without_key_do_nothing(client):
    assert client.post("/api/settings/holidays/preview").json() == {"status": "no_key", "items": []}
    assert client.post("/api/settings/holidays/save").json()["status"] == "no_key"


def test_holiday_preview_does_not_save_and_save_skips_duplicates(holiday_client):
    c, y = holiday_client, holiday_client.this_year
    preview = c.post("/api/settings/holidays/preview").json()
    assert preview["status"] == "ready" and [i["date"] for i in preview["items"]] == [f"{y}-01-01", f"{y}-03-02", f"{y + 1}-01-01"]
    assert not any(i["already_saved"] for i in preview["items"])
    assert c.get("/api/settings/holidays").json()["this_year_count"] == 0
    first = c.post("/api/settings/holidays/save").json()
    assert (first["saved"], first["this_year_count"], first["next_year_count"]) == (3, 2, 1)
    assert c.post("/api/settings/holidays/save").json()["saved"] == 0
    assert all(i["already_saved"] for i in c.post("/api/settings/holidays/preview").json()["items"])
    assert c.get("/api/settings/vacations").json()["items"] == []  # 공휴일은 방학 목록에 섞이지 않습니다


def test_holiday_failure_is_502_without_key_and_requires_login(holiday_client):
    def broken(url, params):
        raise official.OfficialError("network")

    holiday_client.app.state.official_get = broken
    response = holiday_client.post("/api/settings/holidays/preview")
    assert response.status_code == 502 and "fake-holiday-key" not in response.text
    holiday_client.headers.pop("Authorization")
    assert holiday_client.post("/api/settings/holidays/save").status_code == 401
