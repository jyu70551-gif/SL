"""AI 시험 공통 도구. 시험은 실제 OpenAI를 부르지 않고 가짜 LLM만 씁니다. 숫자는 모두 가상입니다."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.ai.client import AiError, LLMResult
from tests.conftest import build_app
from tests.test_home import TEST_PASSWORD, WEDNESDAYS, add_day

TODAY = date(2026, 2, 25)  # 수요일
USUAL = [
    {"담배": (10, 50000), "음료": (17, 30000)},
    {"담배": (11, 54000), "음료": (18, 31000)},
    {"담배": (10, 48000), "음료": (16, 28000)},
    {"담배": (12, 52000), "음료": (17, 30500)},
]


class FakeLLM:
    """미리 정한 응답이나 예외를 순서대로 돌려주는 가짜. 응답이 모자라면 default 를 씁니다."""

    model_name = "fake-model"

    def __init__(self, responses=None, default=None):
        self.responses = list(responses or [])
        self.default = default
        self.calls: list[dict] = []

    def generate_json(self, *, system, user, schema_name, schema, max_output_tokens):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name, "max": max_output_tokens})
        item = self.responses.pop(0) if self.responses else self.default
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(system, user)
        return LLMResult(data=item, input_tokens=120, output_tokens=60, model=self.model_name)


def seed_spike(client, today_values=None):
    """수요일 4번의 평소 + 오늘(2/25) 담배 급증. 점검 항목이 생기는 데이터."""
    for day, values in zip(WEDNESDAYS, USUAL):
        add_day(client, day, values)
    add_day(client, TODAY, today_values or {"담배": (30, 150000), "음료": (17, 30000)})


def seed_quiet(client):
    for day, values in zip(WEDNESDAYS, USUAL):
        add_day(client, day, values)
    add_day(client, TODAY, {"담배": (11, 51000), "음료": (17, 30000)})


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """make_client(llm) -> 로그인된 TestClient. llm 이 None 이면 AI 꺼짐(키 없음)."""
    monkeypatch.setenv("INITIAL_PASSWORD", TEST_PASSWORD)
    opened: list[TestClient] = []

    def _make(llm=None):
        client = TestClient(build_app(tmp_path, llm=llm))
        client.__enter__()
        opened.append(client)
        token = client.post("/api/auth/login", json={"password": TEST_PASSWORD}).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


__all__ = ["AiError", "FakeLLM", "seed_spike", "seed_quiet", "make_client", "TODAY"]
