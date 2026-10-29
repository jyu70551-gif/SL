"""Phase 4 확인 항목 (docs/spec.md 3번). 시험에 쓰인 숫자는 모두 가상입니다.

2026-02-25는 수요일입니다. 같은 요일(수요일): 2/18, 2/11, 2/4, 1/28, 1/21 …
"""
import base64
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import build_app
from tests.test_home import TEST_PASSWORD, WEDNESDAYS, add_day

TODAY = date(2026, 2, 25)
FIXTURE = Path(__file__).parent / "fixtures" / "sample_2026-02-25.csv"

# 평소 수요일: 담배 5만 원 안팎, 음료 3만 원 안팎
USUAL = [
    {"담배": (10, 50000), "음료": (17, 30000)},
    {"담배": (11, 54000), "음료": (18, 31000)},
    {"담배": (10, 48000), "음료": (16, 28000)},
    {"담배": (12, 52000), "음료": (17, 30500)},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def seed(client, today_values):
    for day, values in zip(WEDNESDAYS, USUAL):
        add_day(client, day, values)
    add_day(client, TODAY, today_values)


def names(client):
    return [item["category"] for item in client.get("/api/anomalies").json()["items"]]


def test_requires_login(client):
    bare = TestClient(client.app)
    for path in ["/api/anomalies", "/api/anomalies/series?category=담배", "/api/anomalies/reviewed"]:
        assert bare.get(path).status_code == 401
    assert bare.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-02-25"]}).status_code == 401
    assert bare.post("/api/anomalies/unreview", json={"category": "담배", "date": "2026-02-25"}).status_code == 401


def test_no_uploads(client):
    assert client.get("/api/anomalies").json() == {"has_data": False}


def test_not_enough_days_shows_progress(client):
    for day, values in zip(WEDNESDAYS[:2], USUAL):
        add_day(client, day, values)
    add_day(client, TODAY, {"담배": (50, 900000), "음료": (17, 30000)})
    body = client.get("/api/anomalies").json()
    assert body["status"] == "not_enough"
    assert (body["weeks_used"], body["min_days"], body["needed_more"]) == (2, 3, 1)
    assert body["items"] == []


def test_big_jump_is_listed_and_normal_is_not(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30200)})
    body = client.get("/api/anomalies").json()
    assert body["status"] == "ready"
    assert names(client) == ["담배"]
    flagged = body["items"][0]["flagged"][0]
    assert flagged["date"] == "2026-02-25"
    assert flagged["direction"] == "high"
    assert flagged["amount"] == 150000
    assert flagged["baseline"] == 51000  # 평소 4번의 중간값
    assert flagged["change_pct"] == pytest.approx(194.1, abs=0.1)


def test_big_drop_is_listed(client):
    seed(client, {"담배": (1, 4000), "음료": (17, 30000)})
    item = client.get("/api/anomalies").json()["items"][0]
    assert item["category"] == "담배"
    assert item["flagged"][0]["direction"] == "low"


def test_normal_day_has_empty_list(client):
    seed(client, {"담배": (11, 53000), "음료": (17, 30000)})
    body = client.get("/api/anomalies").json()
    assert body["status"] == "ready"
    assert body["items"] == []


def test_small_gap_is_ignored_even_if_percent_is_large(client):
    # 평소 1천~2천 원짜리 대분류가 4천 원이 된 정도는 경고하지 않습니다. (차이 5천 원 미만)
    for day, v in zip(WEDNESDAYS, [1000, 2000, 1500, 1200]):
        add_day(client, day, {"껌": (1, v)})
    add_day(client, TODAY, {"껌": (3, 4800)})
    assert names(client) == []


def test_category_missing_from_file_counts_as_zero(client):
    seed(client, {"음료": (17, 30000)})  # 오늘 담배 줄이 없음
    item = client.get("/api/anomalies").json()["items"][0]
    assert item["category"] == "담배"
    assert item["flagged"][0]["amount"] == 0
    assert item["flagged"][0]["direction"] == "low"


def test_rarely_sold_category_zero_day_is_normal(client):
    for day, v in zip(WEDNESDAYS, [0, 0, 8000, 0]):
        add_day(client, day, {"담배": (1, 50000), "복권": (1, v)} if v else {"담배": (1, 50000)})
    add_day(client, TODAY, {"담배": (1, 50000)})
    assert names(client) == []


def test_rarely_sold_category_normal_sale_is_normal(client):
    for day, v in zip(WEDNESDAYS, [0, 0, 8000, 0]):
        add_day(client, day, {"담배": (1, 50000), "복권": (1, v)} if v else {"담배": (1, 50000)})
    add_day(client, TODAY, {"담배": (1, 50000), "복권": (1, 9000)})
    assert names(client) == []


def test_rarely_sold_category_big_sale_is_listed(client):
    for day, v in zip(WEDNESDAYS, [0, 0, 8000, 9000]):
        add_day(client, day, {"담배": (1, 50000), "복권": (1, v)} if v else {"담배": (1, 50000)})
    add_day(client, TODAY, {"담배": (1, 50000), "복권": (9, 90000)})
    assert names(client) == ["복권"]


def test_never_sold_category_needs_a_big_sale(client):
    for day in WEDNESDAYS[:4]:
        add_day(client, day, {"담배": (1, 50000)})
    add_day(client, TODAY, {"담배": (1, 50000), "새상품": (1, 3000)})
    assert names(client) == []
    add_day(client, date(2026, 3, 4), {"담배": (1, 50000), "새상품": (5, 60000)})
    # 3/4는 수요일이고 새상품은 한 번도 안 팔렸으므로, 큰 금액이면 올라옵니다.
    assert names(client) == ["새상품"]


def test_different_cutoff_hour_is_not_compared(client):
    for day, values in zip(WEDNESDAYS, USUAL):
        add_day(client, day, values, hour=18)
    add_day(client, TODAY, {"담배": (30, 150000), "음료": (17, 30000)}, hour=22)
    body = client.get("/api/anomalies").json()
    assert body["status"] == "not_enough"
    assert body["weeks_used"] == 0


def test_more_history_is_all_used(client):
    # 아주 오래된 기록까지 평소에 반영됩니다. (4번으로 자르지 않음)
    old = [date(2026, 1, 14), date(2026, 1, 7), date(2025, 12, 31)]
    for day in old:
        add_day(client, day, {"담배": (10, 50000), "음료": (17, 30000)})
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    series = client.get("/api/anomalies/series?category=담배").json()
    assert series["points"][-1]["weeks_used"] == 7


def test_only_last_seven_days_are_listed(client):
    seed(client, {"담배": (11, 53000), "음료": (17, 30000)})
    # 3/4(수)에 이상, 오늘(3/4)로부터 7일 안: 2/25는 목록 기간 밖이 아니라 안. 그 전 이상은 밖.
    add_day(client, date(2026, 3, 11), {"담배": (30, 150000), "음료": (17, 30000)})
    add_day(client, date(2026, 3, 18), {"담배": (11, 53000), "음료": (17, 30000)})
    assert names(client) == []  # 3/11은 3/18보다 7일 이상 앞이라 목록에서 빠짐
    series = client.get("/api/anomalies/series?category=담배").json()
    marked = [p["date"] for p in series["points"] if p["anomaly"]]
    assert marked == ["2026-03-11"]  # 그래프에는 계속 표시됩니다


def test_review_removes_from_list_and_unreview_brings_back(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    res = client.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-02-25"]})
    assert res.status_code == 200
    assert names(client) == []
    reviewed = client.get("/api/anomalies/reviewed").json()["items"]
    assert [(i["category"], i["date"]) for i in reviewed] == [("담배", "2026-02-25")]
    assert reviewed[0]["amount"] == 150000

    assert client.post("/api/anomalies/unreview", json={"category": "담배", "date": "2026-02-25"}).status_code == 200
    assert names(client) == ["담배"]
    assert client.get("/api/anomalies/reviewed").json()["items"] == []


def test_review_twice_is_harmless(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    body = {"category": "담배", "dates": ["2026-02-25"]}
    assert client.post("/api/anomalies/review", json=body).status_code == 200
    assert client.post("/api/anomalies/review", json=body).status_code == 200
    assert len(client.get("/api/anomalies/reviewed").json()["items"]) == 1


def test_review_only_affects_that_date(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    client.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-02-25"]})
    add_day(client, date(2026, 3, 4), {"담배": (30, 160000), "음료": (17, 30000)})
    item = client.get("/api/anomalies").json()["items"][0]
    assert item["category"] == "담배"
    assert [f["date"] for f in item["flagged"]] == ["2026-03-04"]


def test_review_unknown_date_is_rejected_and_saves_nothing(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    res = client.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-02-25", "2026-02-26"]})
    assert res.status_code == 404
    assert client.get("/api/anomalies/reviewed").json()["items"] == []


def test_series_marks_anomaly_and_baseline(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    series = client.get("/api/anomalies/series?category=담배").json()
    assert series["status"] == "ready"
    last = series["points"][-1]
    assert last["date"] == "2026-02-25"
    assert last["anomaly"]["direction"] == "high"
    assert last["anomaly"]["reviewed"] is False
    assert last["typical"] == 51000
    # 평소 기록이 3번 미만이던 앞쪽 날들은 판단하지 않습니다.
    assert series["points"][0]["typical"] is None
    assert client.get("/api/anomalies/series?category=없는분류").status_code == 404


def test_overwrite_clears_reviews_and_rejudges(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    client.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-02-25"]})
    assert client.get("/api/anomalies/reviewed").json()["items"]

    res = client.post(
        "/api/uploads",
        json={
            "filename": "sample_2026-02-25.csv",
            "content_base64": base64.b64encode(FIXTURE.read_bytes()).decode(),
            "cutoff_hour": 22,
            "overwrite": True,
        },
    )
    assert res.status_code == 200, res.text
    assert client.get("/api/anomalies/reviewed").json()["items"] == []


def test_record_saves_reasons_and_memo_and_can_be_edited(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    body = {"category": "담배", "dates": ["2026-02-25"], "reasons": ["promo", "bulk"], "memo": " 단체 주문 "}
    assert client.post("/api/anomalies/review", json=body).status_code == 200
    item = client.get("/api/anomalies/reviewed").json()["items"][0]
    assert item["reasons"] == ["promo", "bulk"]
    assert item["reason_labels"] == ["행사·진열 변경", "단체 구매"]
    assert item["memo"] == "단체 주문"
    point = client.get("/api/anomalies/series?category=담배").json()["points"][-1]
    assert point["record"]["reasons"] == ["promo", "bulk"]

    # 내용을 고쳐 다시 저장하면 한 건이 그대로 갱신됩니다.
    body.update(reasons=["unknown"], memo="")
    client.post("/api/anomalies/review", json=body)
    items = client.get("/api/anomalies/reviewed").json()["items"]
    assert len(items) == 1 and items[0]["reasons"] == ["unknown"] and items[0]["memo"] == ""

    # 선택·메모 없이 다시 눌러도 기존 내용은 지워지지 않습니다.
    client.post("/api/anomalies/review", json={"category": "담배", "dates": ["2026-02-25"]})
    assert client.get("/api/anomalies/reviewed").json()["items"][0]["reasons"] == ["unknown"]


def test_record_rejects_unknown_reason_and_long_memo(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    base = {"category": "담배", "dates": ["2026-02-25"]}
    assert client.post("/api/anomalies/review", json={**base, "reasons": ["없는항목"]}).status_code == 422
    assert client.post("/api/anomalies/review", json={**base, "memo": "가" * 301}).status_code == 422
    assert client.get("/api/anomalies/reviewed").json()["items"] == []


def test_series_reports_dates_used_for_comparison_only_before_the_day(client):
    seed(client, {"담배": (30, 150000), "음료": (17, 30000)})
    points = client.get("/api/anomalies/series?category=담배").json()["points"]
    last = points[-1]
    assert last["baseline_dates"] == [d.isoformat() for d in sorted(WEDNESDAYS[:4])]  # seed는 4번만 넣습니다
    assert all(d < last["date"] for d in last["baseline_dates"])  # 분석 날짜 이후 자료는 쓰지 않습니다
    assert last["weeks_used"] == len(last["baseline_dates"])


def test_chart_baseline_matches_the_judging_baseline_for_rarely_sold_category(client):
    # 평소 대부분 0원인 대분류의 그래프 기준선은 판정에 쓴 기준(팔린 날의 중간값)과 같아야 합니다.
    for day, v in zip(WEDNESDAYS, [0, 0, 8000, 9000]):
        add_day(client, day, {"담배": (1, 50000), "복권": (1, v)} if v else {"담배": (1, 50000)})
    add_day(client, TODAY, {"담배": (1, 50000), "복권": (9, 90000)})
    last = client.get("/api/anomalies/series?category=복권").json()["points"][-1]
    assert last["anomaly"]["baseline"] == last["typical"] == 8500
    assert last["sparse"] is True


def test_series_does_not_fill_missing_dates_with_zero(client):
    seed(client, {"담배": (11, 53000), "음료": (17, 30000)})
    dates = [p["date"] for p in client.get("/api/anomalies/series?category=담배").json()["points"]]
    assert dates == sorted(d.isoformat() for d in [*WEDNESDAYS[:4], TODAY])  # 올린 날짜만 있습니다
