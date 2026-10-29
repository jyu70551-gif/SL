"""Phase 2 확인 항목 (docs/spec.md 2번).

시험용 파일은 tests/fixtures 의 CSV입니다. 상가 프로그램 파일과 같은 모양이지만 숫자는 가상입니다.
"""
import base64
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth
from tests.conftest import build_app
from app.models import DailySale, SalesUpload

FIXTURES = Path(__file__).parent / "fixtures"
TEST_PASSWORD = "test-password-123"
HEADER = "상품코드,대분류,판매수량,판매액,연도,달,일,요일"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_totals(name: str) -> tuple[int, int]:
    """파일의 '합계' 줄에 적힌 (판매수량, 판매액). 대분류를 더한 값과 같아야 합니다."""
    for line in fixture_bytes(name).decode("utf-8-sig").splitlines():
        cols = line.split(",")
        if cols[0] == "-":
            return int(cols[2]), int(cols[3])
    raise AssertionError("합계 줄이 없는 시험 파일")


FEB25_QUANTITY, FEB25_AMOUNT = fixture_totals("sample_2026-02-25.csv")


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    now = auth.utcnow()
    monkeypatch.setattr(auth, "utcnow", lambda: now)
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(build_app(tmp_path)) as c:
        token = c.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


def upload(client, raw: bytes, hour=22, overwrite=False, filename="sample.csv"):
    body = {"filename": filename, "content_base64": b64(raw), "overwrite": overwrite}
    if hour is not None:
        body["cutoff_hour"] = hour
    return client.post("/api/uploads", json=body)


def csv_text(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


def problems_of(res) -> list[str]:
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "invalid_file"
    return res.json()["detail"]["problems"]


def count(client, model) -> int:
    with client.app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(model))


# --- 정상 올리기 -------------------------------------------------------------------------


def test_normal_file_is_saved_and_total_row_is_left_out(client):
    res = upload(client, fixture_bytes("sample_2026-02-25.csv"))
    assert res.status_code == 200
    assert res.json() == {
        "date": "2026-02-25",
        "cutoff_hour": 22,
        "row_count": 24,
        "overwritten": False,
    }
    with client.app.state.session_factory() as db:
        rows = db.scalars(select(DailySale)).all()
        assert len(rows) == 24  # 대분류 24개, "합계" 줄은 저장하지 않음
        assert not any(r.product_code == "-" or r.category == "합계" for r in rows)
        # 대분류 숫자를 더하면 파일의 합계 줄과 같다.
        assert sum(r.quantity for r in rows) == FEB25_QUANTITY
        assert sum(r.amount for r in rows) == FEB25_AMOUNT
        # 앞자리 0이 있는 상품코드가 그대로 보존된다.
        assert {r.product_code for r in rows} >= {"01", "02"}


def test_data_piles_up_across_days(client):
    assert upload(client, fixture_bytes("sample_2026-02-24.csv")).status_code == 200
    assert upload(client, fixture_bytes("sample_2026-02-25.csv")).status_code == 200
    listed = client.get("/api/uploads").json()
    assert [u["date"] for u in listed] == ["2026-02-25", "2026-02-24"]
    assert count(client, DailySale) == 48


def test_file_without_total_row_is_accepted(client):
    raw = csv_text("01,간편식사,3,9600,2026,2,25,수", "02,즉석조리,2,2500,2026,2,25,수")
    assert upload(client, raw).status_code == 200
    assert count(client, DailySale) == 2


def test_korean_excel_file_in_cp949_is_read(client):
    raw = fixture_bytes("sample_2026-02-25.csv").decode("utf-8-sig").encode("cp949")
    res = upload(client, raw)
    assert res.status_code == 200
    with client.app.state.session_factory() as db:
        assert "간편식사" in {r.category for r in db.scalars(select(DailySale))}


def test_numbers_with_thousand_commas_are_accepted(client):
    raw = csv_text('45,담배,11,"49,100",2026,2,25,수')
    assert upload(client, raw).status_code == 200


def test_file_with_other_categories_count_is_still_saved(client):
    raw = csv_text("01,간편식사,1,1000,2026,2,25,수")
    assert upload(client, raw).json()["row_count"] == 1


# --- 시각 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("hour", [None, -1, 24, 99])
def test_missing_or_wrong_hour_is_refused_and_nothing_is_saved(client, hour):
    res = upload(client, fixture_bytes("sample_2026-02-25.csv"), hour=hour)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "invalid_hour"
    assert count(client, SalesUpload) == 0 and count(client, DailySale) == 0


def test_midnight_hour_zero_is_allowed(client):
    assert upload(client, fixture_bytes("sample_2026-02-25.csv"), hour=0).status_code == 200


# --- 잘못된 파일 4가지 ---------------------------------------------------------------------


def test_wrong_column_names_are_refused(client):
    raw = "코드,분류,수량,금액,연도,달,일,요일\n01,간편식사,3,9600,2026,2,25,수\n".encode()
    problems = problems_of(upload(client, raw))
    assert "열 이름이 맞지 않아요." in problems[0]
    assert count(client, DailySale) == 0


def test_missing_column_is_refused(client):
    raw = "상품코드,대분류,판매수량,판매액,연도,달,일\n01,간편식사,3,9600,2026,2,25\n".encode()
    assert "열 이름이 맞지 않아요." in problems_of(upload(client, raw))[0]


def test_extra_column_is_refused(client):
    raw = f"{HEADER},비고\n01,간편식사,3,9600,2026,2,25,수,x\n".encode()
    assert "열 이름이 맞지 않아요." in problems_of(upload(client, raw))[0]


def test_columns_in_a_different_order_are_accepted(client):
    raw = "대분류,상품코드,판매액,판매수량,요일,일,달,연도\n간편식사,01,9600,3,수,25,2,2026\n".encode()
    assert upload(client, raw).status_code == 200


@pytest.mark.parametrize("bad", ["", "abc", "1.5", "3개"])
def test_non_numeric_or_empty_quantity_is_refused(client, bad):
    raw = csv_text(f"01,간편식사,{bad},9600,2026,2,25,수")
    problems = problems_of(upload(client, raw))
    assert any("판매수량" in p for p in problems)
    assert count(client, DailySale) == 0


def test_non_numeric_amount_is_refused(client):
    raw = csv_text("01,간편식사,3,원,2026,2,25,수")
    assert any("판매액" in p for p in problems_of(upload(client, raw)))


def test_impossible_date_is_refused(client):
    raw = csv_text("01,간편식사,3,9600,2026,2,30,금")
    assert any("날짜가 올바르지 않아요" in p for p in problems_of(upload(client, raw)))


def test_mixed_dates_in_one_file_are_refused(client):
    raw = csv_text(
        "01,간편식사,3,9600,2026,2,24,화",
        "01,간편식사,3,9600,2026,2,25,수",
    )
    problems = problems_of(upload(client, raw))
    assert "하루치만" in problems[0]
    assert "2026-02-24" in problems[0] and "2026-02-25" in problems[0]
    assert count(client, SalesUpload) == 0


def test_weekday_that_does_not_match_the_date_is_refused(client):
    raw = csv_text("01,간편식사,3,9600,2026,2,25,월")  # 2026-02-25는 수요일
    problems = problems_of(upload(client, raw))
    assert any("요일이 날짜와 맞지 않아요" in p and "수요일" in p for p in problems)


def test_weekday_written_with_the_word_yoil_is_accepted(client):
    raw = csv_text("01,간편식사,3,9600,2026,2,25,수요일")
    assert upload(client, raw).status_code == 200


def test_error_message_names_the_line_number(client):
    raw = csv_text(
        "01,간편식사,3,9600,2026,2,25,수",
        "02,즉석조리,abc,2500,2026,2,25,수",
    )
    problems = problems_of(upload(client, raw))
    assert problems[0].startswith("3번째 줄")


def test_nothing_is_half_saved_when_one_line_is_wrong(client):
    raw = csv_text(
        "01,간편식사,3,9600,2026,2,25,수",
        "02,즉석조리,abc,2500,2026,2,25,수",
        "11,빵/떡/디저트,2,3900,2026,2,25,수",
    )
    assert upload(client, raw).status_code == 422
    assert count(client, DailySale) == 0 and count(client, SalesUpload) == 0


def test_file_with_only_a_total_row_has_nothing_to_upload(client):
    raw = csv_text("-,합계,66,148850,2026,2,25,수")
    assert "올릴 데이터 줄이 없어요" in problems_of(upload(client, raw))[0]


def test_empty_file_is_refused(client):
    assert "비어 있어요" in problems_of(upload(client, b""))[0]


def test_unreadable_bytes_are_refused(client):
    assert "글자를 읽을 수 없어요" in problems_of(upload(client, b"\xff\xfe\x00\x81\x00"))[0]


def test_broken_upload_content_is_refused(client):
    res = client.post(
        "/api/uploads", json={"filename": "x.csv", "content_base64": "###", "cutoff_hour": 22}
    )
    assert res.status_code == 422


def test_too_large_file_is_refused(client):
    raw = csv_text("01,간편식사,3,9600,2026,2,25,수") + b"#" * (2 * 1024 * 1024 + 1)
    assert upload(client, raw).status_code == 413


# --- 덮어쓰기 -----------------------------------------------------------------------------


def test_same_date_asks_before_overwriting_and_changes_nothing(client):
    upload(client, fixture_bytes("sample_2026-02-25.csv"), hour=22)
    new_raw = csv_text("01,간편식사,99,99999,2026,2,25,수")
    res = upload(client, new_raw, hour=23)
    assert res.status_code == 409
    assert res.json()["detail"] == {"code": "date_exists", "date": "2026-02-25", "cutoff_hour": 22}
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.sum(DailySale.amount))) == FEB25_AMOUNT
        assert db.scalar(select(SalesUpload.cutoff_hour)) == 22


def test_overwrite_replaces_that_date_only(client):
    upload(client, fixture_bytes("sample_2026-02-24.csv"))
    upload(client, fixture_bytes("sample_2026-02-25.csv"), hour=22)
    new_raw = csv_text("01,간편식사,99,99999,2026,2,25,수")
    res = upload(client, new_raw, hour=23, overwrite=True)
    assert res.status_code == 200
    assert res.json()["overwritten"] is True
    with client.app.state.session_factory() as db:
        feb25 = db.scalars(select(DailySale).where(DailySale.sales_date == _d("2026-02-25"))).all()
        assert [(r.category, r.quantity, r.amount) for r in feb25] == [("간편식사", 99, 99999)]
        assert db.scalar(select(SalesUpload.cutoff_hour).where(SalesUpload.sales_date == _d("2026-02-25"))) == 23
        # 다른 날짜(2월 24일)는 그대로
        assert db.scalar(
            select(func.count()).select_from(DailySale).where(DailySale.sales_date == _d("2026-02-24"))
        ) == 24
    assert count(client, SalesUpload) == 2


def test_invalid_file_never_overwrites_existing_data(client):
    upload(client, fixture_bytes("sample_2026-02-25.csv"))
    bad = csv_text("01,간편식사,abc,1,2026,2,25,수")
    assert upload(client, bad, overwrite=True).status_code == 422
    with client.app.state.session_factory() as db:
        assert db.scalar(select(func.sum(DailySale.amount))) == FEB25_AMOUNT


# --- 접근 ---------------------------------------------------------------------------------


def test_upload_and_list_need_the_password(client):
    client.headers.pop("Authorization")
    assert upload(client, fixture_bytes("sample_2026-02-25.csv")).status_code == 401
    assert client.get("/api/uploads").status_code == 401
    assert count(client, SalesUpload) == 0


def _d(text: str):
    from datetime import date

    return date.fromisoformat(text)
