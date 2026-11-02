"""이어지는 변화·0원이 많은 분류 탐지(app/detection.py), 민감도 설정, 확인할 사항 연결 시험. 시험에 쓰인 숫자는 모두 가상입니다."""
import math
import random
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import anomalies, detection
from tests.conftest import build_app
from tests.test_home import TEST_PASSWORD, add_day
from tools import eval_changepoint as cp
from tools import eval_rare
from tools.make_lab_data import holiday_of

START = date(2025, 5, 1)  # 목요일. 휴일 없는 구간


def days(n):
    return [START + timedelta(days=i) for i in range(n)]


def noisy(n, level=20000.0, sd=0.1, seed=1):
    rng = random.Random(seed)
    return [level * math.exp(rng.gauss(0, sd)) for _ in range(n)]


# ---------------------------------------------------------------- 계산 (실험 도구와 같은 결과)
def test_app_detection_matches_the_experiment_tools():
    dates = days(120)
    amounts = [a * (0.55 if 70 <= i < 100 else 1.0) for i, a in enumerate(noisy(120, seed=4))]
    logs = [cp.log_value(a) for a in amounts]
    scored = detection.score_series(logs, dates, skip=holiday_of)
    assert scored == cp.score_series(logs, dates)
    assert detection.alarms_of(scored, amounts, 4.0, 5.0) == cp.alarms_of(scored, amounts, 4.0, 5.0)

    rng = random.Random(2)
    sold = [rng.random() < 0.5 for _ in dates]
    assert detection.occurrence_alarms(sold, dates, 4.0, holiday_of) == cp.occurrence_alarms(sold, dates, 4.0)

    sparse = [a if rng.random() < 0.5 else 0.0 for a in amounts]
    ours = detection.amount_alarms(sparse, dates, 4.0, 5.0, skip=holiday_of)
    assert [(i, kind, direction) for i, kind, direction, _, _ in ours] == cp.amount_alarms(sparse, dates, 4.0, 5.0)

    own = [(1, 2500.0), (2, 3000.0), (1, 2600.0), (2, 3200.0), (1, 2800.0), (3, 5500.0)]
    pooled = own + [(5, 15000.0)] * 3
    for q, a in [(2, 3000.0), (4, 3500.0), (8, 20000.0), (6, 15000.0)]:
        assert detection.is_big_sale(q, a, own, pooled, 3000) == eval_rare.is_big_sale(q, a, own, pooled, 3000)


# ---------------------------------------------------------------- 분류 종류별 탐지
def test_nothing_is_judged_before_28_days_of_history():
    dates = days(28)
    amounts = {"담배": [a * (0.3 if i > 20 else 1.0) for i, a in enumerate(noisy(28))]}
    assert detection.detect(dates, amounts, {"담배": [5] * 28}, "normal") == {}


def test_sustained_drop_in_an_everyday_category_is_flagged_as_trend_and_flat_is_not():
    dates = days(110)
    flat = noisy(110, seed=3)
    drop = [a * (0.6 if i >= 80 else 1.0) for i, a in enumerate(flat)]
    quantities = {"담배": [5] * 110}
    assert detection.detect(dates, {"담배": flat}, quantities, "normal") == {}
    found = detection.detect(dates, {"담배": drop}, quantities, "normal")["담배"]
    assert found and all(i >= 80 and a["direction"] == "low" for i, a in found.items())
    assert {a["kind"] for a in found.values()} <= {"daily", "trend"}
    assert min(found) - 80 < 15  # 며칠~열흘 남짓 안에 알아챔


def test_category_that_stops_selling_is_flagged_as_streak():
    dates = days(120)
    rng = random.Random(8)
    sold = [rng.random() < 0.5 for _ in dates]
    amounts = [rng.choice([6000.0, 8000.0, 9000.0]) if s else 0.0 for s in sold]
    amounts = amounts[:90] + [0.0] * 30
    found = detection.detect(dates, {"간식": amounts}, {"간식": [2 if a else 0 for a in amounts]}, "normal")["간식"]
    streaks = [i for i, a in found.items() if a["kind"] == "streak" and a["direction"] == "low"]
    assert streaks and min(streaks) >= 90 and min(streaks) - 90 < 12


def test_rarely_sold_category_alerts_only_on_a_big_sale():
    dates = days(100)
    amounts = [0.0] * 100
    quantities = [0] * 100
    for i, (q, a) in zip(range(5, 90, 8), [(1, 2600.0), (2, 3000.0), (1, 2500.0), (2, 3100.0), (1, 2700.0), (2, 2900.0), (1, 2600.0), (2, 3000.0), (1, 2500.0), (2, 3100.0), (1, 2800.0)]):
        amounts[i], quantities[i] = a, q
    amounts[95], quantities[95] = 21000.0, 8
    found = detection.detect(dates, {"OTC": amounts}, {"OTC": quantities}, "normal")
    assert list(found["OTC"]) == [95] and found["OTC"][95]["kind"] == "big_sale" and found["OTC"][95]["direction"] == "high"


def test_higher_sensitivity_never_alerts_less():
    dates = days(140)
    rng = random.Random(5)
    amounts = {f"분류{k}": [a * (0.7 if 100 <= i < 125 else 1.0) for i, a in enumerate(noisy(140, 20000.0 + 3000 * k, 0.15, seed=k))] for k in range(4)}
    amounts["간식"] = [rng.choice([5000.0, 7000.0, 9000.0]) if rng.random() < 0.5 else 0.0 for _ in dates]
    quantities = {c: [3 if a else 0 for a in v] for c, v in amounts.items()}
    count = lambda level: sum(len(v) for v in detection.detect(dates, amounts, quantities, level).values())
    assert count("low") <= count("normal") <= count("high")
    assert count("high") > count("low")


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        detection.detect(days(40), {"a": [1.0] * 40}, {"a": [1] * 40}, "extreme")


# ---------------------------------------------------------------- 확인할 사항·설정 연결
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def seed_decline(client, total=110, drop_from=80, factor=0.6):
    """담배가 drop_from 일째부터 평소의 factor 배로 이어지는 분류 하나짜리 기록. 마지막 날이 '오늘'입니다."""
    base = noisy(total, 90000.0, 0.08, seed=11)
    for i, day in enumerate(days(total)):
        amount = int(base[i] * (factor if i >= drop_from else 1.0))
        add_day(client, day, {"담배": (10, amount)}, hour=22)
    return days(total)[-1]


def test_sustained_decline_appears_in_the_list_with_a_plain_sentence(client):
    latest = seed_decline(client)
    data = client.get("/api/anomalies").json()
    flagged = [f for item in data["items"] for f in item["flagged"] if f["kind"] == "trend"]
    assert flagged and flagged[0]["direction"] == "low"
    assert flagged[0]["kind_text"] == "며칠째 평소보다 계속 낮아요"
    assert flagged[0]["basis"] == "최근 며칠의 흐름(요일 효과 제외)"
    assert flagged[0]["amount"] < flagged[0]["baseline"] and flagged[0]["change_pct"] < 0
    assert latest.isoformat() == data["date"]


def test_series_marks_the_new_alarms_too(client):
    seed_decline(client)
    points = client.get("/api/anomalies/series", params={"category": "담배"}).json()["points"]
    marked = [p for p in points if p["anomaly"] and p["anomaly"]["kind"] == "trend"]
    assert marked and marked[0]["anomaly"]["kind_text"]


def test_legacy_mode_keeps_the_old_behaviour(client):
    seed_decline(client)
    with client.app.state.session_factory() as db:
        old = anomalies._analyze(db, anomalies.LEGACY)
        new = anomalies._analyze(db)
    old_trend = [k for k, e in old["judged"].items() if e["anomaly"] and e["anomaly"].get("new_method")]
    new_trend = [k for k, e in new["judged"].items() if e["anomaly"] and e["anomaly"].get("new_method")]
    assert not old_trend and new_trend


def test_a_day_the_old_method_already_flags_keeps_the_old_explanation(client):
    seed_decline(client, total=60, drop_from=59, factor=0.2)  # 마지막 하루만 크게 낮음
    last = ("담배", days(60)[-1])
    with client.app.state.session_factory() as db:
        old = anomalies._analyze(db, anomalies.LEGACY)["judged"][last]["anomaly"]
        new = anomalies._analyze(db)["judged"][last]["anomaly"]
    assert old is not None and old["kind"] == "daily"  # 하루 비교가 먼저 알린다
    assert new == old and not new.get("new_method")  # 새 방법이 같은 칸을 덮어쓰지 않는다


def test_short_history_changes_nothing(client):
    for i, day in enumerate(days(20)):
        add_day(client, day, {"담배": (10, 90000 if i < 19 else 20000)})
    with client.app.state.session_factory() as db:
        assert anomalies._analyze(db)["judged"] == anomalies._analyze(db, anomalies.LEGACY)["judged"]


# ---------------------------------------------------------------- 민감도 설정
def test_sensitivity_requires_login_defaults_to_normal_and_can_be_changed(client):
    assert client.get("/api/settings/sensitivity").json()["level"] == "normal"
    options = client.get("/api/settings/sensitivity").json()["options"]
    assert [o["label"] for o in options] == ["낮음", "보통", "높음"]
    assert client.post("/api/settings/sensitivity", json={"level": "high"}).json()["level"] == "high"
    assert client.get("/api/settings/sensitivity").json()["level"] == "high"
    assert client.post("/api/settings/sensitivity", json={"level": "extreme"}).status_code == 422
    assert client.get("/api/settings/sensitivity").json()["level"] == "high"  # 잘못된 값은 저장되지 않는다
    token = client.headers.pop("Authorization")
    assert client.get("/api/settings/sensitivity").status_code == 401
    assert client.post("/api/settings/sensitivity", json={"level": "low"}).status_code == 401
    client.headers["Authorization"] = token


def test_unknown_stored_value_falls_back_to_normal(client):
    from app.models import AppSetting

    with client.app.state.session_factory() as db:
        db.add(AppSetting(key="sensitivity", value="broken"))
        db.commit()
    assert client.get("/api/settings/sensitivity").json()["level"] == "normal"


def test_lower_sensitivity_lists_no_more_than_higher(client):
    seed_decline(client)
    counts = {}
    for level in ("low", "normal", "high"):
        client.post("/api/settings/sensitivity", json={"level": level})
        counts[level] = sum(len(item["flagged"]) for item in client.get("/api/anomalies").json()["items"])
    assert counts["low"] <= counts["normal"] <= counts["high"]
    assert counts["high"] > 0
