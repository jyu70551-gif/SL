"""날씨 가져오기와 내일 예상 매출 시험. 매출·날씨 숫자는 모두 가상이고, 기상청은 부르지 않고 가짜 응답만 씁니다."""
import math
import random
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import forecast, official, weather
from app.models import DailySale, MarketDay, SalesUpload, WeatherDaily
from tests.conftest import build_app
from tests.test_home import TEST_PASSWORD

START = date(2026, 1, 1)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    forecast._cache.clear()
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def seed(client, days, rain_effect=0.0, temp_effect=0.0, noise=0.05, with_weather=True, seed_no=1):
    """days 일치 가짜 매출. 비 온 날은 매출이 (1+rain_effect)배, 기온 1도당 temp_effect 만큼 달라지도록 심습니다."""
    rng = random.Random(seed_no)
    with client.app.state.session_factory() as db:
        for i in range(days):
            d = START + timedelta(days=i)
            temp = 10 + 8 * math.sin(i / 9)
            rain = 5.0 if rng.random() < 0.25 else 0.0
            total = 100_000 * math.exp(temp_effect * (temp - 10)) * (1 + rain_effect if rain else 1) * math.exp(rng.gauss(0, noise))
            db.add(SalesUpload(sales_date=d, cutoff_hour=8, filename="x.csv", row_count=1, uploaded_at=datetime(2026, 6, 1)))
            db.add(DailySale(sales_date=d, product_code="01", category="담배", quantity=10, amount=round(total)))
            if with_weather:
                db.add(WeatherDaily(day=d, station="가상", avg_temp=temp, rain_mm=rain))
        if with_weather:  # 내일 날씨도 있어야 모형이 날씨를 쓸 수 있습니다
            db.add(WeatherDaily(day=START + timedelta(days=days), station="가상", avg_temp=10 + 8 * math.sin(days / 9), rain_mm=5.0))
        db.commit()


def forecast_of(client):
    return client.get("/api/forecast/tomorrow").json()


# ---------------------------------------------------------------- 회귀식 자체
def test_ridge_recovers_planted_effects_and_shrinks_with_big_penalty():
    rng = random.Random(3)
    rows, y = [], []
    for _ in range(200):
        t, rain = rng.uniform(-5, 25), 1.0 if rng.random() < 0.3 else 0.0
        rows.append([1.0, t, rain])
        y.append(11.0 + 0.01 * t - 0.1 * rain + rng.gauss(0, 0.05))
    weak = forecast.Model(rows, y, lam=0.01)
    assert weak.coef[1] == pytest.approx(0.01, abs=0.003) and weak.coef[2] == pytest.approx(-0.1, abs=0.03)
    strong = forecast.Model(rows, y, lam=1e6)
    assert abs(strong.coef[2]) < 0.005  # 벌금이 아주 크면 효과가 0쪽으로 당겨집니다


def test_lambda_is_chosen_by_leave_one_out_from_the_grid():
    rng = random.Random(5)
    rows = [[1.0, rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(40)]
    exact = [10.0 + 0.5 * r[1] - 0.3 * r[2] for r in rows]  # 잡음 없는 자료는 벌금이 가장 약한 쪽이 낫습니다
    assert forecast.choose_lambda(forecast.Standardized(rows), exact) == forecast.LAMBDAS[0]
    noisy = [10.0 + rng.gauss(0, 0.3) for _ in rows]
    assert forecast.choose_lambda(forecast.Standardized(rows), noisy) in forecast.LAMBDAS


# ---------------------------------------------------------------- 날씨 가져오기
def test_grid_conversion_matches_known_points():
    assert weather.to_grid(37.5665, 126.9780) == (60, 127)  # 서울시청
    assert weather.to_grid(35.1796, 129.0756) == (98, 76)  # 부산시청


def test_nearest_station_and_rain_text():
    station, km = weather.nearest_station(37.37, 126.79)
    assert station[1] == "인천" and 15 < km < 25
    assert [weather.parse_rain(t) for t in ["강수없음", "1mm 미만", "30.0~50.0mm", "50.0mm 이상", "2.5mm"]] == [0.0, 0.5, 40.0, 50.0, 2.5]


def test_fetch_observed_reads_rows_and_skips_blank_temperature():
    def get(url, params):
        rows = [{"tm": "2026-01-01", "stnNm": "가상", "avgTa": "3.5", "sumRn": ""}, {"tm": "2026-01-02", "stnNm": "가상", "avgTa": "", "sumRn": "1.0"},
                {"tm": "2026-01-03", "stnNm": "가상", "avgTa": "-2.0", "sumRn": "7.5"}]
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": rows}}}}

    got = weather.fetch_observed(get, "k", 112, date(2026, 1, 1), date(2026, 1, 3))
    assert [(r["day"], r["temp"], r["rain"]) for r in got] == [(date(2026, 1, 1), 3.5, 0.0), (date(2026, 1, 3), -2.0, 7.5)]
    with pytest.raises(official.OfficialError):
        weather.fetch_observed(get, "", 112, date(2026, 1, 1), date(2026, 1, 3))


def test_forecast_fetch_reads_target_day_only():
    rows = []
    for hour in range(0, 24, 3):
        rows.append({"category": "TMP", "fcstDate": "20261103", "fcstTime": f"{hour:02d}00", "fcstValue": str(hour // 3)})
        rows.append({"category": "POP", "fcstDate": "20261103", "fcstTime": f"{hour:02d}00", "fcstValue": "40" if hour == 6 else "10"})
    rows.append({"category": "PCP", "fcstDate": "20261103", "fcstTime": "0600", "fcstValue": "1mm 미만"})
    rows.append({"category": "TMP", "fcstDate": "20261104", "fcstTime": "0000", "fcstValue": "99"})
    seen = {}

    def get(url, params):
        seen.update(params)
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": rows}}}}

    got = weather.fetch_forecast(get, "k", 37.5665, 126.978, date(2026, 11, 3), datetime(2026, 11, 2, 15, 30))
    assert (seen["nx"], seen["ny"], seen["base_date"], seen["base_time"]) == (60, 127, "20261102", "1400")
    assert got["temp"] == pytest.approx(3.5) and got["rain_mm"] == 0.5 and got["pop"] == 40
    assert weather.fetch_forecast(get, "k", 37.5, 127.0, date(2026, 11, 9), datetime(2026, 11, 2, 15, 30)) is None  # 예보 범위 밖


def test_weather_sync_saves_only_missing_days_and_reports_station(client, monkeypatch):
    monkeypatch.setenv("WEATHER_PAST_API_KEY", "fake-key")
    seed(client, 5, with_weather=False)
    assert client.get("/api/settings/weather").json()["status"] == "no_location"
    client.post("/api/settings/store", json={"latitude": 37.37, "longitude": 126.79})
    seen = {}

    def fake(url, params):
        seen.update(params)
        rows = [{"tm": (START + timedelta(days=i)).isoformat(), "stnNm": "인천", "avgTa": str(i), "sumRn": "0"} for i in range(5)]
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": rows}}}}

    client.app.state.official_get = fake
    first = client.post("/api/settings/weather/sync").json()
    assert (first["added"], first["asked"], first["station"], first["days"], first["missing"]) == (5, 5, "인천", 5, 0)
    assert seen["stnIds"] == 112 and "fake-key" not in str(first)
    assert client.post("/api/settings/weather/sync").json()["added"] == 0  # 이미 있는 날은 다시 받지 않습니다


def test_saving_the_location_fills_weather_and_moving_drops_other_station_rows(client, monkeypatch):
    monkeypatch.setenv("WEATHER_PAST_API_KEY", "fake-key")
    seed(client, 5, with_weather=False)
    def fake(url, params):
        name = "인천" if params["stnIds"] == 112 else "다른관측소"
        rows = [{"tm": (START + timedelta(days=i)).isoformat(), "stnNm": name, "avgTa": str(i), "sumRn": "0"} for i in range(5)]
        return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": rows}}}}

    client.app.state.official_get = fake
    client.post("/api/settings/store", json={"latitude": 37.37, "longitude": 126.79})
    assert client.get("/api/settings/weather").json()["days"] == 5  # 설정에서 누르지 않아도 위치를 저장하면 채워집니다
    assert client.get("/api/home/summary").status_code == 200
    client.post("/api/settings/store", json={"latitude": 36.35, "longitude": 127.38})  # 대전: 다른 관측소
    after = client.get("/api/settings/weather").json()
    assert after["stations"] == ["다른관측소"]  # 옛 관측소 날씨는 지워지고 새 관측소 것으로 다시 채워집니다


def test_weather_sync_requires_key_location_and_login(client, monkeypatch):
    assert client.post("/api/settings/weather/sync").json() == {"status": "no_location"}
    client.post("/api/settings/store", json={"latitude": 37.37, "longitude": 126.79})
    assert client.post("/api/settings/weather/sync").json() == {"status": "no_key"}
    client.headers.pop("Authorization")
    assert client.post("/api/settings/weather/sync").status_code == 401


# ---------------------------------------------------------------- 내일 예상 매출
def test_no_uploads_and_too_few_days(client):
    assert forecast_of(client) == {"status": "no_data"}
    seed(client, 8)
    out = forecast_of(client)
    assert out["status"] == "not_enough" and out["days"] == 8


def test_model_is_used_when_weather_really_matters(client):
    seed(client, 150, rain_effect=-0.35, temp_effect=0.02, noise=0.04)
    out = forecast_of(client)
    assert out["status"] == "ready" and out["method"] == "model" and out["weather_used"]
    assert out["backtest"]["model_error_pct"] < out["backtest"]["baseline_error_pct"] * 0.95
    assert out["low"] < out["center"] < out["high"]
    assert out["target_date"] == (START + timedelta(days=150)).isoformat() and out["weather"]["source"] == "observed"


def test_baseline_is_used_when_nothing_beats_it_and_says_so(client):
    seed(client, 150, rain_effect=0.0, temp_effect=0.0, noise=0.2)  # 날씨와 상관없는 자료
    out = forecast_of(client)
    assert out["method"] == "baseline" and not out["weather_used"] and out["factors"] == []
    assert any("평소 기준" in n for n in out["notes"])


def test_short_history_has_a_range_but_never_claims_the_model_is_better(client):
    seed(client, 20, noise=0.1)
    out = forecast_of(client)
    assert out["status"] == "ready" and out["method"] == "baseline"
    assert out["low"] is not None and out["low"] <= out["center"] <= out["high"]


def test_missing_weather_is_reported_and_not_used(client):
    seed(client, 150, rain_effect=-0.35, temp_effect=0.02, noise=0.04, with_weather=False)
    out = forecast_of(client)
    assert out["status"] == "ready" and out["weather"] is None and not out["weather_used"]
    assert any("날씨" in n for n in out["notes"])


def test_market_day_label_comes_from_saved_days(client):
    seed(client, 150, noise=0.04)
    assert "장날" not in forecast_of(client)["labels"]
    with client.app.state.session_factory() as db:
        db.add_all(MarketDay(day=d) for d in range(1, 32))  # 모든 날이 장날 → 목표 날짜에도 붙습니다
        db.commit()
    assert "장날" in forecast_of(client)["labels"]


def test_forecast_requires_login(client):
    client.headers.pop("Authorization")
    assert client.get("/api/forecast/tomorrow").status_code == 401

# ---------------------------------------------------------------- 전국 관측소
def test_station_table_is_complete_and_sane():
    from app.asos_stations import STATIONS
    ids = [s[0] for s in STATIONS]
    assert len(STATIONS) == 97 and len(set(ids)) == 97 and ids == sorted(ids)
    assert all(isinstance(s[0], int) and s[1] and 33 < s[2] < 39 and 124 < s[3] < 132 for s in STATIONS)  # 한반도와 제주 범위


@pytest.mark.parametrize("lat, lon, expected", [
    (36.1972, 126.6857, "보령"),  # 충남 보령
    (34.9507, 127.4872, "순천"),  # 전남 순천
    (33.4996, 126.5312, "제주"),  # 제주시
    (37.4846, 130.9057, "울릉도"),  # 울릉도 (독도 쪽 바다 위는 제외)
    (35.1796, 129.0756, "부산"),  # 부산시청
    (37.5665, 126.9780, "서울"),  # 서울시청
])
def test_nearest_station_works_across_the_country(lat, lon, expected):
    station, km = weather.nearest_station(lat, lon)
    assert station[1] == expected and km < weather.MAX_STATION_KM


def test_far_from_every_station_weather_is_not_fetched(client, monkeypatch):
    monkeypatch.setenv("WEATHER_PAST_API_KEY", "fake-key")
    seed(client, 5, with_weather=False)
    client.post("/api/settings/store", json={"latitude": 33.0, "longitude": 132.0})  # 허용 범위 안에서 관측소가 가장 먼 바다 위 지점(약 360km)
    calls = []
    client.app.state.official_get = lambda url, params: calls.append(params) or {}
    info = client.get("/api/settings/weather").json()
    assert info["status"] == "too_far" and info["station"]["distance_km"] > weather.MAX_STATION_KM and info["max_km"] == weather.MAX_STATION_KM
    result = client.post("/api/settings/weather/sync").json()
    assert result["status"] == "too_far" and result["added"] == 0 and calls == []  # 기상청을 부르지도 않음
    assert client.get("/api/settings/weather").json()["days"] == 0
