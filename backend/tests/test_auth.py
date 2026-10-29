"""Phase 1 확인 항목 (docs/plan.md, docs/spec.md 1번).

여기 쓰인 비밀번호는 시험용 가짜 값이며 실제 서비스와 무관합니다.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app

TEST_PASSWORD = "test-password-123"


class Clock:
    def __init__(self):
        self.now = auth.utcnow()

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(auth, "utcnow", lambda: c.now)
    return c


@pytest.fixture
def client(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    with TestClient(create_app()) as c:
        yield c


def login(client, password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_is_open_and_shows_no_data(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_protected_address_rejects_without_password(client):
    assert client.get("/api/auth/me").status_code == 401


def test_protected_address_rejects_made_up_token(client):
    assert client.get("/api/auth/me", headers=bearer("not-a-real-token")).status_code == 401


def test_correct_password_opens_the_door(client):
    res = login(client)
    assert res.status_code == 200
    token = res.json()["token"]
    assert client.get("/api/auth/me", headers=bearer(token)).status_code == 200


def test_wrong_password_is_rejected_and_counts_down(client):
    res = login(client, "wrong-password")
    assert res.status_code == 401
    assert res.json()["detail"] == {"code": "wrong_password", "remaining_attempts": 4}


def test_five_wrong_in_a_row_locks_for_ten_minutes(client, clock):
    for _ in range(4):
        assert login(client, "wrong-password").status_code == 401
    fifth = login(client, "wrong-password")
    assert fifth.status_code == 429
    assert fifth.json()["detail"]["code"] == "locked"

    # 잠긴 동안에는 맞는 비밀번호도 받지 않는다.
    clock.advance(minutes=9)
    assert login(client).status_code == 429

    # 10분이 지나면 풀리고, 맞는 비밀번호로 들어간다.
    clock.advance(minutes=2)
    assert login(client).status_code == 200


def test_correct_password_resets_the_wrong_count(client):
    for _ in range(3):
        login(client, "wrong-password")
    assert login(client).status_code == 200
    res = login(client, "wrong-password")
    assert res.json()["detail"]["remaining_attempts"] == 4


def test_wrong_count_starts_over_after_a_lock_ends(client, clock):
    for _ in range(5):
        login(client, "wrong-password")
    clock.advance(minutes=11)
    res = login(client, "wrong-password")
    assert res.status_code == 401
    assert res.json()["detail"]["remaining_attempts"] == 4


def test_login_is_remembered_for_30_days_then_asks_again(client, clock):
    token = login(client).json()["token"]
    clock.advance(days=29, hours=23)
    assert client.get("/api/auth/me", headers=bearer(token)).status_code == 200
    clock.advance(hours=2)
    assert client.get("/api/auth/me", headers=bearer(token)).status_code == 401


def test_password_is_not_stored_as_plain_text(client):
    from app.models import AuthState

    with client.app.state.session_factory() as db:
        stored = db.get(AuthState, 1).password_hash
    assert TEST_PASSWORD not in stored
    assert stored.startswith("scrypt$")


def test_login_asks_to_set_password_when_none_is_configured(tmp_path, monkeypatch, clock):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setenv("INITIAL_PASSWORD", "")
    with TestClient(create_app()) as c:
        res = c.post("/api/auth/login", json={"password": "anything-goes"})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "not_configured"


def test_too_short_initial_password_stops_the_server(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'short.db'}")
    monkeypatch.setenv("INITIAL_PASSWORD", "short")
    with pytest.raises(RuntimeError):
        create_app()
