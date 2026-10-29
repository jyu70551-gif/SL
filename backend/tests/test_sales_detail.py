"""총매출 분석 (홈 매출 요약의 상세). 시험에 쓰인 숫자는 모두 가상입니다.

2026-02-25는 수요일입니다. 비교 자료는 요일을 가리지 않고, 같은 시각까지 집계한 오늘 이전의 모든 날입니다.
"""
import math
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.sales_detail import evaluate
from app.stats import t_cdf, t_ppf
from tests.conftest import build_app
from tests.test_home import TEST_PASSWORD, WEDNESDAYS, add_day

TODAY = date(2026, 2, 25)
USUAL = [100000, 102000, 98000, 101000, 99000]  # 평소 수요일 총매출


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def seed(client, today_total, history=USUAL, hour=22):
    for day, total in zip(WEDNESDAYS, history):
        add_day(client, day, {"담배": (10, total)}, hour=hour)
    add_day(client, TODAY, {"담배": (10, today_total)}, hour=hour)


def detail(client):
    res = client.get("/api/sales/detail")
    assert res.status_code == 200, res.text
    return res.json()


# ---- t 분포 계산이 표준 값과 맞는지 (외부 라이브러리 없이 직접 계산하므로 꼭 확인)
@pytest.mark.parametrize(
    "df,expected",
    [(1, 12.7062047), (2, 4.3026527), (3, 3.1824463), (4, 2.7764451), (6, 2.4469119), (10, 2.2281389), (30, 2.0422725)],
)
def test_t_quantile_matches_standard_table(df, expected):
    assert t_ppf(0.975, df) == pytest.approx(expected, abs=1e-5)


def test_t_cdf_known_values():
    assert t_cdf(0, 5) == pytest.approx(0.5)
    assert t_cdf(2.0, 10) == pytest.approx(0.963306, abs=1e-6)
    assert t_cdf(-2.0, 10) == pytest.approx(1 - 0.963306, abs=1e-6)


def test_evaluate_matches_hand_calculation():
    history = [100000, 102000, 98000, 101000, 99000]
    result = evaluate(history, 100000)
    logs = [math.log(v) for v in history]
    mu = sum(logs) / 5
    sd = math.sqrt(sum((v - mu) ** 2 for v in logs) / 4)
    t = (math.log(100000) - mu) / (sd * math.sqrt(1 + 1 / 5))
    assert result["t"] == pytest.approx(t, abs=0.01)
    assert result["df"] == 4
    assert result["center"] == pytest.approx(math.exp(mu), abs=1)
    assert result["low"] < result["center"] < result["high"]


# ---- 판정
def test_requires_login(client):
    assert TestClient(client.app).get("/api/sales/detail").status_code == 401


def test_no_uploads(client):
    assert client.get("/api/sales/detail").json() == {"has_data": False}


def test_big_increase_is_significant(client):
    seed(client, 160000)
    test = detail(client)["test"]
    assert test["status"] == "ready"
    assert test["verdict"] == "increase"
    assert test["p_value"] < 0.05
    assert test["side"] == "high"
    assert test["rank_below"] == 5  # 기록 5번 모두 오늘보다 낮았음


def test_big_decrease_is_significant(client):
    seed(client, 55000)
    test = detail(client)["test"]
    assert test["verdict"] == "decrease"
    assert test["p_value"] < 0.05
    assert test["side"] == "low"
    assert test["rank_below"] == 0


def test_usual_day_is_not_significant(client):
    seed(client, 101500)
    test = detail(client)["test"]
    assert test["status"] == "ready"
    assert test["verdict"] == "none"
    assert test["p_value"] >= 0.05
    assert test["low"] <= 101500 <= test["high"]


def test_range_never_goes_below_zero_for_noisy_history(client):
    # 흔들림이 큰 평소(실제 데이터처럼)에서도 평소 범위는 0원 아래로 내려가지 않습니다.
    seed(client, 90000, history=[130000, 170000, 110000, 150000, 95000])
    test = detail(client)["test"]
    assert test["scale"] == "log"
    assert test["low"] > 0


def test_few_data_is_flagged_as_reference_only(client):
    seed(client, 101500, history=[100000, 102000, 98000])  # 기록 3번
    test = detail(client)["test"]
    assert test["n"] == 3
    assert test["few_data"] is True


def test_not_enough_days_shows_progress_and_no_verdict(client):
    for day, total in zip(WEDNESDAYS[:2], USUAL):
        add_day(client, day, {"담배": (10, total)})
    add_day(client, TODAY, {"담배": (10, 900000)})
    test = detail(client)["test"]
    assert test["status"] == "not_enough"
    assert (test["n"], test["needed_more"]) == (2, 1)
    assert "verdict" not in test  # 자료가 모자라면 임의로 판정하지 않습니다


def test_no_variation_is_not_judged(client):
    seed(client, 130000, history=[100000] * 5)
    assert detail(client)["test"]["status"] == "no_variation"


def test_zero_today_falls_back_to_raw_amounts(client):
    seed(client, 0)
    test = detail(client)["test"]
    assert test["status"] == "ready"
    assert test["scale"] == "raw"
    assert test["low"] >= 0
    assert test["verdict"] == "decrease"


# ---- 같은 시각끼리만, 오늘 이전 자료만
def test_other_cutoff_hour_is_excluded_from_comparison_and_chart(client):
    for day, total in zip(WEDNESDAYS, USUAL):
        add_day(client, day, {"담배": (10, total)}, hour=18)
    add_day(client, TODAY, {"담배": (10, 160000)}, hour=22)
    body = detail(client)
    assert body["test"]["status"] == "not_enough"
    assert body["test"]["n"] == 0
    assert body["excluded_other_hour"] == 5
    assert [p["date"] for p in body["points"]] == [TODAY.isoformat()]


def test_only_earlier_records_are_used(client):
    seed(client, 160000)
    add_day(client, date(2026, 2, 26), {"담배": (10, 5000000)})  # 오늘보다 나중 날짜: 오늘이 아니므로 최신이 바뀜
    body = detail(client)
    # 가장 최근 날짜(2/26)가 '오늘'이 되고, 그보다 앞선 날만 쓰입니다.
    assert body["date"] == "2026-02-26"
    assert body["used_dates"] == sorted(d.isoformat() for d in [*WEDNESDAYS[:5], TODAY])
    assert all(d < body["date"] for d in body["used_dates"])  # 분석 날짜 이후 자료는 쓰지 않습니다
    assert body["test"]["n"] == len(body["used_dates"])


def test_all_accumulated_records_are_used_not_just_recent_four(client):
    seed(client, 101500)
    assert detail(client)["test"]["n"] == 5  # 홈은 최근 4번이지만, 여기는 쌓인 전체


def test_weekday_does_not_matter(client):
    seed(client, 101500)
    # 수요일이 아닌 날(화·목·금)도 같은 시각까지 집계했다면 평소 분포에 들어갑니다.
    for day, total in [(date(2026, 2, 24), 99500), (date(2026, 2, 19), 100500), (date(2026, 2, 20), 100200)]:
        add_day(client, day, {"담배": (10, total)}, hour=22)
    body = detail(client)
    assert body["test"]["n"] == 8
    assert {"2026-02-24", "2026-02-19", "2026-02-20"} <= set(body["used_dates"])


def test_chart_points_mark_used_days_and_today(client):
    seed(client, 101500)
    add_day(client, date(2026, 2, 24), {"담배": (10, 80000)}, hour=22)  # 화요일(오늘 이전)
    body = detail(client)
    flags = {p["date"]: (p["used"], p["is_today"]) for p in body["points"]}
    assert flags["2026-02-25"] == (False, True)
    assert flags["2026-02-24"] == (True, False)
    assert flags["2026-02-18"] == (True, False)
    # 올리지 않은 날짜는 0원으로 채우지 않습니다.
    assert "2026-02-19" not in flags
