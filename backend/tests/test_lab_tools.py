"""랩 도구(가짜 데이터 만들기·탐지 평가)와 "시연용" 표시 시험. 시험에 쓰는 매출 CSV는 모두 가상 숫자입니다."""
import json
import math
import random
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import make_engine, make_session_factory
from app.models import DailySale, ReviewedAnomaly, SalesUpload
from tests.conftest import build_app
from tools import eval_detection, make_lab_data
from tools.make_lab_data import MIN_EVENT_GAP, build, holiday_of, truth_path

CATEGORIES = [("45", "담배", 90000), ("31", "음료", 14000), ("01", "간편식사", 9000), ("12", "과자류", 4000), ("02", "즉석조리", 3000), ("33", "주류", 2500)]
HEADER = "상품코드,대분류,판매수량,판매액,연도,달,일,요일\r\n"


def fake_source(tmp_path, days=14, seed=7):
    """가상 숫자로 만든 '실제처럼 보이는' 날짜별 CSV. 월·화·수만 있습니다."""
    rng = random.Random(seed)
    folder = tmp_path / "csv"
    folder.mkdir()
    day = date(2026, 1, 5)  # 월요일
    made = 0
    while made < days:
        if day.weekday() < 3:
            weekday = "월화수"[day.weekday()]
            rows, total_q, total_a = [], 0, 0
            for code, name, base in CATEGORIES:
                amount = int(base * rng.uniform(0.6, 1.4) // 50 * 50) if rng.random() > 0.15 else 0
                qty = max(1, amount // 1500) if amount else 0
                rows.append(f"{code},{name},{qty},{amount},{day.year},{day.month},{day.day},{weekday}")
                total_q, total_a = total_q + qty, total_a + amount
            body = "".join(f"{r}\r\n" for r in rows)
            (folder / f"sales_{day.isoformat()}.csv").write_text("﻿" + HEADER + body + f"-,합계,{total_q},{total_a},{day.year},{day.month},{day.day},{weekday}\r\n", encoding="utf-8", newline="")
            made += 1
        day += timedelta(days=1)
    return folder


@pytest.fixture
def source(tmp_path):
    return fake_source(tmp_path)


def lab(tmp_path, source, seed=1, name="lab.db"):
    out = tmp_path / name
    meta = build(source, out, date(2025, 9, 1), seed)
    return out, meta


def read(db_path):
    sf = make_session_factory(make_engine(f"sqlite:///{db_path}"))
    with sf() as db:
        uploads = {u.sales_date: u for u in db.scalars(select(SalesUpload))}
        cells = {(d, c): (q, a) for d, c, q, a in db.execute(select(DailySale.sales_date, DailySale.category, DailySale.quantity, DailySale.amount))}
        records = list(db.scalars(select(ReviewedAnomaly)))
    return uploads, cells, records


def test_real_days_are_kept_exactly_and_never_overlap_synthetic(tmp_path, source):
    out, meta = lab(tmp_path, source)
    uploads, cells, _ = read(out)
    real_files = sorted(source.glob("sales_*.csv"))
    real_days = {date.fromisoformat(f.stem.split("_")[1]) for f in real_files}
    assert {d for d, u in uploads.items() if u.filename != "synthetic"} == real_days
    assert all(u.filename == "synthetic" for d, u in uploads.items() if d not in real_days)
    for f in real_files:  # 실제 날의 금액은 원본 CSV와 완전히 같다
        day = date.fromisoformat(f.stem.split("_")[1])
        for line in f.read_text(encoding="utf-8").splitlines()[1:]:
            code, name, qty, amount, *_ = line.split(",")
            if name != "합계":
                assert cells[(day, name)] == (int(qty), int(amount))


def test_every_date_in_range_exists_once_with_every_category_and_one_cutoff(tmp_path, source):
    out, meta = lab(tmp_path, source)
    uploads, cells, _ = read(out)
    start, end = date.fromisoformat(meta["기간"][0]), date.fromisoformat(meta["기간"][1])
    assert sorted(uploads) == [start + timedelta(days=i) for i in range((end - start).days + 1)]
    assert {u.cutoff_hour for u in uploads.values()} == {8}
    assert all(len({c for (dd, c) in cells if dd == d}) == len(CATEGORIES) for d in uploads)
    assert all(u.row_count == len(CATEGORIES) for u in uploads.values())


def test_all_seven_weekdays_are_filled(tmp_path, source):
    out, _ = lab(tmp_path, source)
    uploads, _, _ = read(out)
    assert {d.weekday() for d in uploads} == set(range(7))  # 실제에는 월·화·수뿐이어도 목~일이 채워진다


def test_same_seed_gives_same_data_and_different_seed_differs(tmp_path, source):
    a, _ = lab(tmp_path, source, seed=3, name="a.db")
    b, _ = lab(tmp_path, source, seed=3, name="b.db")
    c, _ = lab(tmp_path, source, seed=4, name="c.db")
    assert read(a)[1] == read(b)[1]
    assert read(a)[1] != read(c)[1]


def test_injected_events_are_meaningful_labelled_and_only_on_synthetic_days(tmp_path, source):
    out, meta = lab(tmp_path, source, seed=2)
    uploads, cells, _ = read(out)
    events = meta["정답이 표시된 이상"]
    assert events
    for e in events:
        d = date.fromisoformat(e["date"])
        assert uploads[d].filename == "synthetic"  # 실제 날은 건드리지 않는다
        assert holiday_of(d) is None
        assert e["kind"] in ("spike", "drop", "zero")
        assert e["expected_gap"] >= MIN_EVENT_GAP  # 탐지가 일부러 무시하는 작은 금액이 아니다
        if e["kind"] == "zero":
            assert cells[(d, e["category"])] == (0, 0)
    assert truth_path(out).exists()
    assert json.loads(truth_path(out).read_text(encoding="utf-8"))["정답이 표시된 이상"] == events


def test_at_least_one_event_in_the_last_week_so_home_shows_something(tmp_path, source):
    out, meta = lab(tmp_path, source, seed=2)
    latest = date.fromisoformat(meta["기간"][1])
    assert any(latest - timedelta(days=7) <= date.fromisoformat(e["date"]) < latest for e in meta["정답이 표시된 이상"])


def test_fake_owner_records_exist_only_for_older_synthetic_events(tmp_path, source):
    out, meta = lab(tmp_path, source, seed=2)
    _, _, records = read(out)
    latest = date.fromisoformat(meta["기간"][1])
    event_cells = {(e["category"], e["date"]) for e in meta["정답이 표시된 이상"]}
    assert records
    for r in records:
        assert (r.category, r.sales_date.isoformat()) in event_cells
        assert r.sales_date < latest - timedelta(days=7)  # 최근 일주일의 이상은 아직 기록 전(점검에 보이도록)
        assert r.source in ("form", "ai") and r.reasons


def test_synthetic_totals_are_in_the_same_range_as_the_real_ones(tmp_path, source):
    out, meta = lab(tmp_path, source)
    uploads, cells, _ = read(out)
    totals = {d: sum(a for (dd, _), (_, a) in cells.items() if dd == d) for d in uploads}
    real = [totals[d] for d, u in uploads.items() if u.filename != "synthetic"]
    fake = [totals[d] for d, u in uploads.items() if u.filename == "synthetic" and holiday_of(d) is None]
    assert 0.6 < (sum(fake) / len(fake)) / (sum(real) / len(real)) < 1.6


def test_tool_refuses_a_non_db_output_path_and_missing_source(tmp_path, monkeypatch, source):
    monkeypatch.setattr(sys, "argv", ["make_lab_data.py", "--source", str(source), "--out", str(tmp_path / "x.txt")])
    with pytest.raises(SystemExit):
        make_lab_data.main()
    monkeypatch.setattr(sys, "argv", ["make_lab_data.py", "--source", str(tmp_path / "없는폴더"), "--out", str(tmp_path / "y.db")])
    with pytest.raises(SystemExit):
        make_lab_data.main()


def test_lab_never_touches_the_real_database(tmp_path, source, monkeypatch):
    """랩 DB는 SQLite 파일로만 만들어지고, DB_* (Supabase) 설정을 읽지 않는다."""
    for key in ("DB_HOST", "DB_USER", "DB_PASSWORD"):
        monkeypatch.setenv(key, "should-not-be-used")
    out, _ = lab(tmp_path, source)
    assert out.exists() and out.read_bytes()[:6] == b"SQLite"


def test_evaluation_runs_and_counts_sensible_numbers(tmp_path, source):
    out, meta = lab(tmp_path, source, seed=5)
    sf = make_session_factory(make_engine(f"sqlite:///{out}"))
    truth = meta["정답이 표시된 이상"]
    with sf() as db:
        files = {u.sales_date: u.filename for u in db.scalars(select(SalesUpload))}
        current = eval_detection.evaluate_rule(db, files, truth, [3.0], "current")
        alt = eval_detection.evaluate_rule(db, files, truth, [3.0], "alt")
    for run in (current, alt):
        r = run[0]
        assert 0 <= r["hit"] <= r["events"]
        assert r["cells"] > 0 and r["false_alarms"] <= r["cells"]
    merged = eval_detection.merge([current, current])
    assert merged[0]["recall"] == pytest.approx(current[0]["hit"] / current[0]["events"])


def test_evaluation_restores_the_score_threshold(tmp_path, source):
    from app import anomalies

    out, meta = lab(tmp_path, source, seed=5)
    before = anomalies.SCORE_THRESHOLD
    sf = make_session_factory(make_engine(f"sqlite:///{out}"))
    with sf() as db:
        files = {u.sales_date: u.filename for u in db.scalars(select(SalesUpload))}
        eval_detection.evaluate_rule(db, files, meta["정답이 표시된 이상"], [2.0, 5.0], "current")
    assert anomalies.SCORE_THRESHOLD == before  # 평가가 앱의 기준값을 바꾼 채로 남기면 안 된다


def test_changepoint_detector_catches_a_sustained_shift_but_not_a_flat_series():
    from tools import eval_changepoint as cp

    start = date(2025, 5, 1)  # 휴일이 없는 구간
    dates = [start + timedelta(days=i) for i in range(70)]
    rng = random.Random(1)
    flat = [20000 * math.exp(rng.gauss(0, 0.1)) for _ in dates]
    shifted = [a * (0.5 if i >= 45 else 1.0) for i, a in enumerate(flat)]
    config = (None, 5.0)  # CUSUM만
    assert not cp.alarms_of(cp.score_series([cp.log_value(a) for a in flat], dates), flat, *config)
    alarms = cp.alarms_of(cp.score_series([cp.log_value(a) for a in shifted], dates), shifted, *config)
    assert alarms and all(direction == -1 and i >= 45 for i, _, direction in alarms)  # 급감 쪽으로, 변화 이후에만


def test_occurrence_cusum_flags_a_stockout_but_not_normal_gaps():
    from tools import eval_changepoint as cp

    start = date(2025, 5, 1)
    dates = [start + timedelta(days=i) for i in range(100)]
    rng = random.Random(3)
    normal = [rng.random() < 0.5 for _ in dates]  # 절반쯤 팔리는 분류
    assert not cp.occurrence_alarms(normal, dates, 5.0)
    stockout = normal[:60] + [False] * 40  # 60일째부터 안 팔림
    alarms = cp.occurrence_alarms(stockout, dates, 4.0)
    assert alarms and all(direction == -1 and i >= 60 for i, direction in alarms)


def test_rare_category_rule_alerts_only_on_unusually_large_sales():
    from tools.eval_rare import is_big_sale

    own = [(1, 2500.0), (2, 3000.0), (1, 2600.0), (2, 3200.0), (1, 2800.0), (3, 5500.0)]
    pooled = own + [(5, 15000.0)] * 3
    assert not is_big_sale(2, 3000.0, own, pooled, 3000)  # 평소 판매
    assert not is_big_sale(4, 3500.0, own, pooled, 3000)  # 수량은 많지만 금액이 수량 많았던 날만큼 안 됨
    assert is_big_sale(8, 20000.0, own, pooled, 3000)  # 기록이 있고 최대보다 훨씬 많이 팔림
    assert not is_big_sale(8, 5000.0, own, pooled, 3000)  # 금액 차이가 최소 금액 미만
    assert is_big_sale(9, 20000.0, [], pooled, 3000)  # 이 분류 기록이 없어도 합친 기록으로 판단
    assert not is_big_sale(2, 2000.0, [], [], 3000)  # 비교할 기록이 전혀 없으면 수량 5 미만은 알리지 않음


def test_final_evaluation_helpers_split_categories_and_build_shifts():
    from tools import eval_final as ef

    assert [ef.tier_of(s, 100) for s in (95, 50, 10, 0)] == ["dense", "mid", "rare", "none"]
    dates = [date(2025, 5, 1) + timedelta(days=i) for i in range(100)]
    qty, amt = [2] * 100, [10000.0] * 100
    q2, a2, window, sign = ef.make_shift("dense", "×0.6", qty, amt, dates, 40, random.Random(1))
    assert sign == -1 and list(window) == list(range(40, 68)) and a2[40] == 6000.0 and a2[39] == 10000.0 and a2[68] == 10000.0
    q2, a2, window, sign = ef.make_shift("rare", 5, qty, amt, dates, 40, random.Random(1))
    assert sign == 1 and list(window) == [40] and q2[40] == 10 and a2[40] == 50000.0 and a2[41] == 10000.0


def test_sensitivity_levels_get_stricter_as_sensitivity_drops_and_filter_by_score():
    from tools import eval_sensitivity as es

    low, mid, high = (es.LEVELS[k] for k in ("낮음", "보통", "높음"))
    assert low["old"] > mid["old"] > high["old"]  # 현재 방식의 점수 기준은 낮을수록 민감
    assert low["dense"][1] > mid["dense"][1] > high["dense"][1] and low["occ"] > mid["occ"] > high["occ"]
    assert low["rare_gap"] > mid["rare_gap"] > high["rare_gap"]
    raw = {("A", date(2025, 5, 1)): (1, 3.4), ("B", date(2025, 5, 1)): (-1, 2.6), ("C", date(2025, 5, 1)): (1, None)}
    assert set(es.current_at(raw, 2.5)) == set(raw)
    assert set(es.current_at(raw, 3.0)) == {("A", date(2025, 5, 1)), ("C", date(2025, 5, 1))}  # 점수 없는 항목(늘 0원이던 분류)은 유지
    assert set(es.current_at(raw, 4.0)) == {("C", date(2025, 5, 1))}


def test_changepoint_detector_ignores_holidays_and_uses_only_earlier_days():
    from tools import eval_changepoint as cp

    start = date(2025, 5, 1)
    dates = [start + timedelta(days=i) for i in range(60)]
    values = [cp.log_value(20000.0)] * 60
    scored = cp.score_series(values, dates)
    assert all(s is None for s in scored[: cp.MIN_HISTORY])  # 앞선 기록이 모자라면 판단하지 않는다
    values2 = values[:50] + [cp.log_value(90000.0)] * 10  # 뒤쪽을 바꿔도 앞쪽 점수는 그대로여야 한다
    assert cp.score_series(values2, dates)[:50] == scored[:50]


# ---------------------------------------------------------------- 시연용 로그인
def test_open_login_only_when_the_lab_tool_turns_it_on(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", "test-password-123")
    app = build_app(tmp_path, name="normal2.db")
    with TestClient(app) as client:  # 일반 서버: 틀린 비밀번호는 거절
        assert client.post("/api/auth/login", json={"password": "아무거나12345"}).status_code == 401
    app.state.open_login = True  # serve_lab.py 가 켜는 설정
    with TestClient(app) as client:
        token = client.post("/api/auth/login", json={"password": "x"}).json()["token"]
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


# ---------------------------------------------------------------- 시연용 표시
def test_health_marks_lab_servers_only(tmp_path, monkeypatch):
    monkeypatch.setenv("INITIAL_PASSWORD", "test-password-123")
    with TestClient(build_app(tmp_path, name="normal.db")) as client:
        assert client.get("/api/health").json() == {"status": "ok"}  # 평소에는 달라지지 않는다
    monkeypatch.setenv("SL_LAB_MODE", "1")
    with TestClient(build_app(tmp_path, name="lab.db")) as client:
        assert client.get("/api/health").json() == {"status": "ok", "lab": True}
