"""Phase 3 확인 항목 (docs/spec.md 4번, 5번, 8-2).

2026-02-25는 수요일입니다. 같은 요일(수요일) 데이터는 2/18, 2/11, 2/4, 1/28, 1/21 …입니다.
시험에 쓰인 숫자는 모두 가상입니다.
"""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.models import DailySale, SalesUpload
from tests.conftest import build_app

TEST_PASSWORD = "test-password-123"
TODAY = date(2026, 2, 25)  # 수요일


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def add_day(client, day: date, categories: dict[str, tuple[int, int]], hour=22):
    """하루치 데이터를 바로 넣는다. categories = {대분류: (수량, 판매액)}"""
    with client.app.state.session_factory() as db:
        db.add(
            SalesUpload(
                sales_date=day,
                cutoff_hour=hour,
                filename="t.csv",
                row_count=len(categories),
                uploaded_at=datetime(2026, 3, 1),
            )
        )
        for i, (name, (qty, amount)) in enumerate(categories.items()):
            db.add(
                DailySale(
                    sales_date=day,
                    product_code=f"{i:02d}",
                    category=name,
                    quantity=qty,
                    amount=amount,
                )
            )
        db.commit()


def summary(client):
    res = client.get("/api/home/summary")
    assert res.status_code == 200, res.text
    return res.json()


WEDNESDAYS = [date(2026, 2, 18), date(2026, 2, 11), date(2026, 2, 4), date(2026, 1, 28), date(2026, 1, 21)]


# --- 비어 있을 때 ------------------------------------------------------------------------


def test_no_files_yet(client):
    assert summary(client) == {"has_data": False}


def test_needs_the_password(client):
    client.headers.pop("Authorization")
    assert client.get("/api/home/summary").status_code == 401


# --- 오늘 총매출·판매수량 -------------------------------------------------------------------


def test_today_totals_are_the_sum_of_categories(client):
    add_day(client, TODAY, {"간편식사": (3, 9000), "음료": (10, 15000), "담배": (5, 30000)})
    data = summary(client)
    assert data["has_data"] is True
    assert data["date"] == "2026-02-25"
    assert data["weekday"] == "수"
    assert data["cutoff_hour"] == 22
    assert data["today"] == {"total_quantity": 18, "total_amount": 54000}


def test_same_category_on_several_lines_is_added_up(client):
    with client.app.state.session_factory() as db:
        db.add(SalesUpload(sales_date=TODAY, cutoff_hour=22, filename="", row_count=2, uploaded_at=datetime(2026, 3, 1)))
        db.add_all(
            [
                DailySale(sales_date=TODAY, product_code="01", category="간편식사", quantity=2, amount=4000),
                DailySale(sales_date=TODAY, product_code="01", category="간편식사", quantity=3, amount=6000),
            ]
        )
        db.commit()
    data = summary(client)
    assert data["today"] == {"total_quantity": 5, "total_amount": 10000}
    assert data["instant_food"][0]["today_quantity"] == 5


def test_today_is_the_latest_date_not_the_latest_upload(client):
    # 2/25 파일을 먼저 올리고, 예전 날짜(2/24)를 나중에 올려도 "오늘"은 2/25
    add_day(client, TODAY, {"음료": (1, 1000)})
    add_day(client, date(2026, 2, 24), {"음료": (9, 9000)})
    data = summary(client)
    assert data["date"] == "2026-02-25"
    assert data["today"]["total_quantity"] == 1


# --- 같은 요일 비교 ----------------------------------------------------------------------


def test_comparison_needs_more_data_at_first(client):
    add_day(client, TODAY, {"음료": (10, 10000)})
    add_day(client, WEDNESDAYS[0], {"음료": (8, 8000)})  # 같은 요일 1번뿐
    comparison = summary(client)["comparison"]
    assert comparison["status"] == "not_enough"
    assert comparison["weeks_used"] == 1
    assert comparison["needed_more"] == 2
    assert "baseline_amount" not in comparison


def test_comparison_appears_after_three_same_weekdays(client):
    add_day(client, TODAY, {"음료": (12, 12000)})
    for day, qty in zip(WEDNESDAYS[:3], [10, 10, 10]):
        add_day(client, day, {"음료": (qty, qty * 1000)})
    comparison = summary(client)["comparison"]
    assert comparison["status"] == "ready"
    assert comparison["weeks_used"] == 3
    assert comparison["needed_more"] == 0
    assert comparison["baseline_quantity"] == 10
    assert comparison["baseline_amount"] == 10000
    assert comparison["quantity_change_pct"] == 20.0
    assert comparison["amount_change_pct"] == 20.0


def test_only_the_latest_four_same_weekdays_are_averaged(client):
    add_day(client, TODAY, {"음료": (10, 10000)})
    values = [10, 10, 10, 10, 100]  # 가장 오래된 5번째(100)는 평균에서 빠진다
    for day, qty in zip(WEDNESDAYS, values):
        add_day(client, day, {"음료": (qty, qty * 1000)})
    comparison = summary(client)["comparison"]
    assert comparison["weeks_used"] == 4
    assert comparison["baseline_quantity"] == 10
    assert comparison["quantity_change_pct"] == 0.0


def test_other_weekdays_are_ignored(client):
    add_day(client, TODAY, {"음료": (10, 10000)})
    for day in [date(2026, 2, 24), date(2026, 2, 23), date(2026, 2, 22)]:  # 화·월·일
        add_day(client, day, {"음료": (999, 999000)})
    assert summary(client)["comparison"]["weeks_used"] == 0


def test_days_with_a_different_cutoff_hour_are_not_compared(client):
    add_day(client, TODAY, {"음료": (10, 10000)}, hour=22)
    for day in WEDNESDAYS[:3]:
        add_day(client, day, {"음료": (10, 10000)}, hour=18)  # 오후 6시까지의 매출
    comparison = summary(client)["comparison"]
    assert comparison["status"] == "not_enough"
    assert comparison["weeks_used"] == 0
    assert comparison["excluded_other_hour"] == 3


def test_percent_change_is_empty_when_usual_value_is_zero(client):
    add_day(client, TODAY, {"음료": (5, 5000)})
    for day in WEDNESDAYS[:3]:
        add_day(client, day, {"음료": (0, 0)})
    comparison = summary(client)["comparison"]
    assert comparison["status"] == "ready"
    assert comparison["quantity_change_pct"] is None
    assert comparison["amount_change_pct"] is None


def test_decrease_is_negative(client):
    add_day(client, TODAY, {"음료": (8, 8000)})
    for day in WEDNESDAYS[:3]:
        add_day(client, day, {"음료": (10, 10000)})
    assert summary(client)["comparison"]["amount_change_pct"] == -20.0


# --- 즉석식품 요약 ------------------------------------------------------------------------


def test_instant_food_lists_the_two_categories_in_order(client):
    add_day(client, TODAY, {"간편식사": (4, 8000), "즉석조리": (2, 3000), "음료": (9, 9000)})
    items = summary(client)["instant_food"]
    assert [i["category"] for i in items] == ["간편식사", "즉석조리"]
    assert [i["today_quantity"] for i in items] == [4, 2]


def test_instant_food_not_enough_data_keeps_today_number(client):
    add_day(client, TODAY, {"간편식사": (4, 8000)})
    item = summary(client)["instant_food"][0]
    assert item["status"] == "not_enough"
    assert item["today_quantity"] == 4
    assert item["needed_more"] == 3
    assert "verdict" not in item


@pytest.mark.parametrize(
    "today_qty, verdict",
    [(9, "high"), (6, "normal"), (5, "normal"), (8, "normal"), (4, "low"), (0, "low")],
)
def test_instant_food_verdict_against_the_usual_range(client, today_qty, verdict):
    add_day(client, TODAY, {"간편식사": (today_qty, today_qty * 2000)})
    for day, qty in zip(WEDNESDAYS[:3], [5, 6, 8]):  # 평소 범위 5~8
        add_day(client, day, {"간편식사": (qty, qty * 2000)})
    item = summary(client)["instant_food"][0]
    assert item["range_min"] == 5 and item["range_max"] == 8
    assert item["verdict"] == verdict


def test_missing_instant_food_category_counts_as_zero(client):
    add_day(client, TODAY, {"음료": (3, 3000)})  # 간편식사 줄이 파일에 없음
    item = summary(client)["instant_food"][0]
    assert item["today_quantity"] == 0
