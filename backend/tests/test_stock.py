"""입출고 소진율·증량 검토 신호 시험 (docs/stock.md). 모든 숫자는 가상입니다."""
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from app import stock
from app.stock import DayRecord
from tools import make_stock_data

START = date(2026, 9, 1)


def rec(i, sold, received=10, opening=0, discarded=None, promo=False, hour=None, closing=None):
    """i번째 날의 기록. 폐기를 안 적으면 팔고 남은 것은 모두 폐기된 것으로 봅니다(소비기한 하루)."""
    left = opening + received - sold
    disc = left if discarded is None else discarded
    return DayRecord(START + timedelta(days=i), "P1", "가상 도시락", "간편식사", opening, received, sold, disc,
                     left - disc if closing is None else closing, promo=promo, sold_out_hour=hour)


def run(sold_list, **kw):
    return [rec(i, s, **kw) for i, s in enumerate(sold_list)]


# ---------------------------------------------------------------- 소진율 정의
def test_sell_through_uses_what_could_actually_be_sold_not_the_received_amount():
    r = DayRecord(START, "P1", "가상", "간편식사", opening=3, received=7, sold=8, discarded=0, closing=2)
    assert r.available == 10
    assert r.sell_through == pytest.approx(0.8)  # 판매 ÷ 입고(8÷7=114%)가 아니라 판매 ÷ (기초재고+입고)
    assert r.waste_rate == 0
    assert DayRecord(START, "P1", "가상", "간편식사", 0, 0, 0, 0, 0).sell_through is None  # 나눌 수량이 없으면 계산하지 않음


# ---------------------------------------------------------------- 신호
def test_repeated_high_sell_through_with_early_stockouts_is_an_increase_review():
    out = stock.judge(run([10, 10, 10, 10, 10], hour=17))
    assert out["signal"] == "increase_review"
    assert (out["high_days"], out["stockout_days"]) == (5, 5) and out["stockout_basis"] == "품절 시각"
    assert out["window"]["sold"] == 50 and out["window"]["available"] == 50  # 수량을 함께 보여 줍니다
    assert out["params"]["high_sell_through"] == 0.90  # 초기값을 결과에 같이 담습니다


def test_selling_out_right_at_closing_is_balanced_not_an_increase_review():
    records = [rec(i, 10, hour=21) for i in range(5)]  # 판매 종료(22시) 직전에 다 팔림
    out = stock.judge(records)
    assert out["signal"] == "balanced" and out["stockout_days"] == 0


def test_without_sold_out_times_it_is_estimated_and_says_so():
    out = stock.judge(run([10, 10, 10, 10, 10]))
    assert out["signal"] == "increase_review" and "추정" in out["stockout_basis"]


def test_sold_out_time_known_somewhere_means_only_times_count_as_stockouts():
    records = [rec(0, 10, hour=15), rec(1, 10), rec(2, 10), rec(3, 10), rec(4, 10)]  # 다 팔린 날은 많지만 일찍 품절은 하루뿐
    out = stock.judge(records)
    assert out["stockout_days"] == 1 and out["signal"] == "balanced"


def test_repeated_waste_with_low_sell_through_is_a_decrease_review():
    out = stock.judge(run([5, 4, 6, 5, 5]))
    assert out["signal"] == "decrease_review" and out["waste_days"] == 5
    assert out["window"]["discarded"] == 25


def test_no_signal_when_the_numbers_are_in_between():
    assert stock.judge(run([8, 8, 8, 8, 8], discarded=0, closing=2))["signal"] == "none"


def test_promo_days_are_left_out_and_a_promo_only_high_is_reported_separately():
    records = [rec(0, 8), rec(1, 10, promo=True), rec(2, 8), rec(3, 8), rec(4, 10, promo=True), rec(5, 8), rec(6, 8), rec(7, 10, promo=True)]
    out = stock.judge(records, as_of=START + timedelta(days=7))
    assert out["window"]["days"] == 5 and out["signal"] == "promo_only"  # 행사 3번 빼고 평소 5번만 봅니다
    records = [rec(i, 8, received=11) for i in range(5)] + [rec(5, 11, received=11, promo=True), rec(6, 11, received=11, promo=True)]
    assert stock.judge(records)["signal"] == "promo_only"
    assert stock.judge(records)["window"]["days"] == 5  # 행사 날은 평소 판단에 섞이지 않습니다


def test_too_few_days_or_tiny_quantities_are_not_judged():
    assert stock.judge(run([10, 10, 10, 10]))["signal"] == "insufficient"  # 4번뿐
    tiny = [rec(i, 2, received=2) for i in range(5)]  # 2개 중 2개 판매
    out = stock.judge(tiny)
    assert out["signal"] == "insufficient" and out["dropped_small_days"] == 5
    many_but_small = [rec(i, 5, received=5) for i in range(5)]  # 날마다 5개: 합 25개로 하한(30개) 미만
    assert stock.judge(many_but_small)["signal"] == "insufficient"


def test_as_of_ignores_later_days():
    records = run([10] * 5, hour=17) + [rec(5 + i, 3) for i in range(5)]
    assert stock.judge(records, as_of=START + timedelta(days=4))["signal"] == "increase_review"
    assert stock.judge(records)["signal"] != "increase_review"


def test_the_signal_never_says_must_increase():
    names = {stock.judge(run([10] * 5, hour=17))["signal"], *[stock.judge(run(s))["signal"] for s in ([5] * 5, [8] * 5)]}
    assert not any("must" in n or "required" in n for n in names)
    assert "증량 필요" not in "".join(stock.judge(run([10] * 5, hour=17))["reasons"])


# ---------------------------------------------------------------- 파일 읽기
def test_csv_is_parsed_and_bad_rows_are_skipped():
    head = ",".join(stock.FIELDS)
    row = "2026-09-01,S001,P1,가상 도시락,간편식사,0,10,2000,2026-09-02,가상식품,8,2,0,3000,1,0,10,19"
    bad_date, no_code, negative = row.replace("2026-09-01", "없음"), row.replace(",P1,", ",,"), row.replace(",0,10,", ",0,-3,")
    got = stock.parse_stock_csv("\n".join([head, row, bad_date, no_code, negative]))
    assert len(got) == 1
    r = got[0]
    assert (r.product, r.sold, r.discarded, r.promo, r.sold_out_hour, r.available) == ("P1", 8, 2, True, 19, 10)


# ---------------------------------------------------------------- 가짜 자료로 규칙 확인
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_fake_stock_data_gets_the_planted_signals(seed):
    rows, truth = make_stock_data.build(seed)
    records = stock.parse_stock_csv(make_stock_data.to_csv(rows))
    got = {code: result["signal"] for code, result in stock.judge_all(records).items()}
    assert got == truth


def test_judge_all_groups_by_product_and_carries_names():
    rows, _ = make_stock_data.build(3)
    out = stock.judge_all(stock.parse_stock_csv(make_stock_data.to_csv(rows)))
    assert set(out) == set(make_stock_data.SCENARIOS) and out["F001"]["name"] == "참치마요 삼각김밥"
    assert replace(rec(0, 3), promo=True).promo


# ---------------------------------------------------------------- 저장과 화면용 요약, 주소
def test_summary_orders_signals_and_carries_the_numbers():
    rows, _ = make_stock_data.build(3)
    out = stock.summarize(stock.parse_stock_csv(make_stock_data.to_csv(rows)))
    assert out["status"] == "ready" and out["date"] == (make_stock_data.START + timedelta(days=39)).isoformat()
    signals = [p["signal"] for p in out["products"]]
    assert signals == sorted(signals, key=stock.SIGNAL_ORDER.get) and signals[0] == "increase_review"
    first = out["products"][0]
    assert first["window"]["days"] == 5 and first["window"]["sell_through_pct"] == 100 and first["window"]["waste_pct"] == 0
    assert first["today"]["available"] == 10 and first["today"]["sell_through_pct"] == 100
    tiny = next(p for p in out["products"] if p["signal"] == "insufficient")
    assert tiny["window"]["days"] == 0 and tiny["today"]["available"] == 2  # 판단은 안 하지만 그날 숫자는 보여 줍니다


def test_summary_without_data():
    assert stock.summarize([]) == {"status": "no_data", "products": []}


def test_records_roundtrip_through_the_database_and_summary_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.conftest import build_app
    from tests.test_home import TEST_PASSWORD

    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    app = build_app(tmp_path)
    with TestClient(app) as c:
        assert c.get("/api/stock/summary").status_code == 401
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        assert c.get("/api/stock/summary").json()["status"] == "no_data"
        rows, truth = make_stock_data.build(3)
        records = stock.parse_stock_csv(make_stock_data.to_csv(rows))
        with app.state.session_factory() as db:
            assert stock.save_records(db, records) == len(records)
            assert stock.save_records(db, records[:5]) == 5  # 같은 날짜·상품은 덮어씁니다
            assert len(stock.load_records(db)) == len(records)
        got = c.get("/api/stock/summary").json()
        assert {p["product"]: p["signal"] for p in got["products"]} == truth


# ---------------------------------------------------------------- 진행 중 주기, 자료 검증, 행사 비교, 문구
def test_a_cycle_still_in_progress_is_not_judged_and_shown_as_selling():
    records = run([10] * 5, hour=17)
    last = START + timedelta(days=4)
    morning = datetime(last.year, last.month, last.day, 8, 0)
    out = stock.summarize(records, morning)
    assert out["date"] == (last - timedelta(days=1)).isoformat()  # 오늘 기록은 아직 끝나지 않아서 제외
    item = out["products"][0]
    assert item["selling_now"] == {"sold": 10} and item["window"]["days"] == 4 and item["signal"] == "insufficient"
    evening = datetime(last.year, last.month, last.day, 23, 0)
    done = stock.summarize(records, evening)  # 판매 종료 뒤에는 오늘 기록도 완료된 주기
    assert done["date"] == last.isoformat() and done["products"][0]["selling_now"] is None
    assert stock.summarize(records, None)["date"] == last.isoformat()  # 시각을 모르면 모두 완료로 봅니다


def test_rows_whose_stock_numbers_do_not_add_up_are_left_out_and_counted():
    good = run([10] * 4, hour=17)
    broken = DayRecord(START + timedelta(days=4), "P1", "가상 도시락", "간편식사", 0, 10, 10, 0, 3)  # 10 = 10 + 0 + 3 이 아님
    assert not broken.reconciles
    out = stock.judge(good + [broken])
    assert out["dropped_mismatch"] == 1 and out["window"]["days"] == 4 and out["signal"] == "insufficient"


def test_promo_and_non_promo_results_are_reported_side_by_side():
    records = [rec(i, 8, received=11, discarded=2) for i in range(5)] + [rec(5, 11, received=11, discarded=0, promo=True), rec(6, 11, received=11, discarded=0, promo=True)]
    out = stock.judge(records)
    assert out["signal"] == "promo_only"
    assert out["window"]["days"] == 5 and out["window"]["sell_through"] == pytest.approx(0.727, abs=0.001)
    assert out["promo_window"]["days"] == 2 and out["promo_window"]["sell_through"] == 1.0
    assert len(out["window_days"]) == 5 and all(not d["promo"] for d in out["window_days"])
    assert [d["promo"] for d in out["promo_days"]] == [True, True]


def test_carryover_is_flagged_because_the_same_stock_counts_in_several_days():
    carry = [rec(i, 8, received=6, opening=4, discarded=0, closing=2) for i in range(5)]
    assert all(r.reconciles for r in carry)
    assert stock.judge(carry)["carryover"] is True
    assert stock.judge(run([10] * 5, hour=17))["carryover"] is False


def test_the_reason_says_whether_stockouts_are_recorded_times_or_only_guessed():
    with_hours = " ".join(stock.judge(run([10] * 5, hour=17))["reasons"])
    assert "기록된 품절 시각" in with_hours and "행사 없이 판매를 마친 최근 5회" in with_hours
    guessed = " ".join(stock.judge(run([10] * 5))["reasons"])
    assert "추정" in guessed and "구분하지 못해요" in guessed


def test_summary_endpoint_marks_demo_data(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.conftest import build_app
    from tests.test_home import TEST_PASSWORD

    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    app = build_app(tmp_path)
    with TestClient(app) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        assert c.get("/api/stock/summary").json()["demo"] is False
        monkeypatch.setenv("SL_LAB_MODE", "1")
        assert c.get("/api/stock/summary").json()["demo"] is True
