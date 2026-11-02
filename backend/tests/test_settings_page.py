"""설정 화면(spec 7장): 점포 위치·장날, 방학 기간, 비밀번호 바꾸기. 시험에 쓰인 숫자와 이름은 모두 가상입니다."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.settings import merged_vacations
from tests.conftest import build_app
from tests.test_home import TEST_PASSWORD


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def vacation(client, start, end):
    return client.post("/api/settings/vacations", json={"start_date": start, "end_date": end})


# ---------------------------------------------------------------- 로그인 필요
def test_every_settings_address_needs_the_password(client):
    client.headers.pop("Authorization")
    assert client.get("/api/settings/store").status_code == 401
    assert client.post("/api/settings/store", json={}).status_code == 401
    assert client.get("/api/settings/vacations").status_code == 401
    assert vacation(client, "2026-07-20", "2026-08-20").status_code == 401
    assert client.put("/api/settings/vacations/1", json={}).status_code == 401
    assert client.delete("/api/settings/vacations/1").status_code == 401
    assert client.post("/api/settings/password", json={}).status_code == 401


# ---------------------------------------------------------------- 점포 위치와 장날
def test_store_starts_empty_and_saves_place_and_market_days(client):
    assert client.get("/api/settings/store").json() == {"city": "", "dong": "", "market_days": [], "latitude": None, "longitude": None}
    saved = client.post("/api/settings/store", json={"city": " 가상시 ", "dong": "가상동", "market_days": [28, 3, 8, 13, 18, 23, 8]}).json()
    assert saved == {"city": "가상시", "dong": "가상동", "market_days": [3, 8, 13, 18, 23, 28], "latitude": None, "longitude": None}  # 공백 제거, 중복 제거, 순서대로
    assert client.get("/api/settings/store").json() == saved


def test_store_can_be_cleared_and_rejects_bad_values_without_changing_anything(client):
    client.post("/api/settings/store", json={"city": "가상시", "dong": "가상동", "market_days": [3, 8]})
    for bad in ({"city": "가" * 41}, {"market_days": [0]}, {"market_days": [32]}, {"market_days": [3, -1]}):
        assert client.post("/api/settings/store", json=bad).status_code == 422
    assert client.get("/api/settings/store").json() == {"city": "가상시", "dong": "가상동", "market_days": [3, 8], "latitude": None, "longitude": None}
    assert client.post("/api/settings/store", json={}).json() == {"city": "", "dong": "", "market_days": [], "latitude": None, "longitude": None}


# ---------------------------------------------------------------- 처음 설정 안내
def test_first_login_needs_setup_until_a_location_is_saved_or_it_is_skipped(client):
    assert client.get("/api/settings/setup").json() == {"has_location": False, "dismissed": False, "needs_setup": True}
    client.post("/api/settings/store", json={"city": "가상시", "latitude": 37.5, "longitude": 127.0})
    assert client.get("/api/settings/setup").json() == {"has_location": True, "dismissed": False, "needs_setup": False}  # 등록하면 더 안 보냄
    client.post("/api/settings/store", json={"city": "가상시"})  # 위치를 지우면
    assert client.get("/api/settings/setup").json()["needs_setup"] is True  # 건너뛴 적이 없으면 다시 안내


def test_skipping_stops_the_redirect_but_keeps_the_home_reminder(client):
    skipped = client.post("/api/settings/setup/dismiss").json()
    assert skipped == {"has_location": False, "dismissed": True, "needs_setup": False}  # 홈 안내는 has_location=false 로 계속
    assert client.post("/api/settings/setup/dismiss").json() == skipped  # 두 번 눌러도 같다
    assert client.get("/api/settings/setup").json() == skipped  # 저장되어 있다(다른 기기에서도 같다)


def test_setup_endpoints_need_the_password(client):
    client.headers.pop("Authorization")
    assert client.get("/api/settings/setup").status_code == 401
    assert client.post("/api/settings/setup/dismiss").status_code == 401


# ---------------------------------------------------------------- 방학
def test_vacations_can_be_added_listed_edited_and_deleted(client):
    assert client.get("/api/settings/vacations").json() == {"items": []}
    items = vacation(client, "2026-12-24", "2027-02-28").json()["items"]
    items = vacation(client, "2026-07-20", "2026-08-20").json()["items"]
    assert [(i["start_date"], i["end_date"]) for i in items] == [("2026-07-20", "2026-08-20"), ("2026-12-24", "2027-02-28")]  # 시작일 순서
    summer = items[0]["id"]
    edited = client.put(f"/api/settings/vacations/{summer}", json={"start_date": "2026-07-25", "end_date": "2026-08-25"}).json()["items"]
    assert (edited[0]["start_date"], edited[0]["end_date"]) == ("2026-07-25", "2026-08-25")
    left = client.delete(f"/api/settings/vacations/{summer}").json()["items"]
    assert [(i["start_date"], i["end_date"]) for i in left] == [("2026-12-24", "2027-02-28")]
    assert client.get("/api/settings/vacations").json()["items"] == left  # 저장된 값이 남아 있다


def test_same_day_vacation_and_past_and_future_dates_are_allowed(client):
    assert vacation(client, "2026-05-05", "2026-05-05").status_code == 200  # 하루짜리
    assert vacation(client, "2019-01-01", "2019-01-31").status_code == 200  # 과거
    assert vacation(client, "2031-07-01", "2031-07-31").status_code == 200  # 미래


@pytest.mark.parametrize("start,end,code", [("2026-08-20", "2026-07-20", "end_before_start"), ("", "2026-07-20", "invalid_date"), ("2026-07-20", "", "invalid_date"), ("2026-13-40", "2026-07-20", "invalid_date"), ("abc", "def", "invalid_date")])
def test_bad_vacation_is_not_saved_and_the_old_list_stays(client, start, end, code):
    vacation(client, "2026-07-20", "2026-08-20")
    response = vacation(client, start, end)
    assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert len(client.get("/api/settings/vacations").json()["items"]) == 1


def test_bad_edit_keeps_the_saved_dates_and_unknown_id_is_404(client):
    item = vacation(client, "2026-07-20", "2026-08-20").json()["items"][0]
    assert client.put(f"/api/settings/vacations/{item['id']}", json={"start_date": "2026-09-01", "end_date": "2026-08-01"}).status_code == 422
    assert client.get("/api/settings/vacations").json()["items"][0]["start_date"] == "2026-07-20"
    assert client.put("/api/settings/vacations/9999", json={"start_date": "2026-07-01", "end_date": "2026-07-02"}).status_code == 404
    assert client.delete("/api/settings/vacations/9999").status_code == 404


def test_overlapping_vacations_are_both_saved_but_counted_once(client):
    vacation(client, "2026-07-20", "2026-08-10")
    vacation(client, "2026-08-01", "2026-08-20")
    vacation(client, "2026-12-24", "2027-01-05")
    assert len(client.get("/api/settings/vacations").json()["items"]) == 3  # 입력한 그대로 남는다
    with client.app.state.session_factory() as db:
        assert merged_vacations(db) == [(date(2026, 7, 20), date(2026, 8, 20)), (date(2026, 12, 24), date(2027, 1, 5))]


def test_a_vacation_inside_another_does_not_shrink_the_merged_one(client):
    vacation(client, "2026-07-01", "2026-08-31")
    vacation(client, "2026-07-10", "2026-07-12")
    with client.app.state.session_factory() as db:
        assert merged_vacations(db) == [(date(2026, 7, 1), date(2026, 8, 31))]


# ---------------------------------------------------------------- 비밀번호 바꾸기
NEW_PASSWORD = "another-password-456"


def change(client, current=TEST_PASSWORD, new=NEW_PASSWORD, again=None):
    return client.post("/api/settings/password", json={"current": current, "new": new, "new_again": new if again is None else again})


def login(client, password):
    return TestClient(client.app).post("/api/auth/login", json={"password": password}).status_code


def test_changing_the_password_replaces_the_old_one(client):
    assert change(client).json() == {"ok": True}
    assert login(client, TEST_PASSWORD) == 401  # 이전 비밀번호로는 못 들어간다
    assert login(client, NEW_PASSWORD) == 200


def test_current_session_stays_and_other_devices_are_signed_out(client):
    other = TestClient(client.app)
    other_token = other.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
    assert other.get("/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}).status_code == 200
    assert change(client).status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # 지금 쓰는 기기는 그대로
    assert other.get("/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}).status_code == 401  # 다른 기기는 로그아웃


@pytest.mark.parametrize(
    "kwargs,status,code",
    [
        ({"current": "wrong-password-000"}, 400, "wrong_password"),
        ({"again": "different-password-1"}, 422, "mismatch"),
        ({"new": "short", "again": "short"}, 422, "too_short"),
        ({"new": "1234567", "again": "1234567"}, 422, "too_short"),
    ],
)
def test_bad_password_change_is_refused_and_the_old_password_stays(client, kwargs, status, code):
    response = change(client, **kwargs)
    assert response.status_code == status and response.json()["detail"]["code"] == code
    assert login(client, TEST_PASSWORD) == 200
    assert login(client, NEW_PASSWORD) == 401


def test_exactly_eight_characters_are_allowed_and_no_mix_is_required(client):
    assert change(client, new="abcdefgh").status_code == 200
    assert login(client, "abcdefgh") == 200
