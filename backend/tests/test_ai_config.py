"""Phase 5-1: AI 설정, 사용 가능 상태, 사용량 한도, 서킷 브레이커 (SDD 4, 6.9)."""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import config
from app.ai import service as service_module
from app.ai.client import AiError
from app.ai.service import AiService, month_start_utc
from app.db import Base, make_engine, make_session_factory
from tests.ai_fakes import FakeLLM, make_client  # noqa: F401  (fixture)

SECRET = "sk-test-SECRET-1234567890"


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'ai.db'}")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def call(service, **override):
    args = dict(kind="briefing", system="s", user="u", schema_name="x", schema={}, max_output_tokens=10)
    args.update(override)
    return service.generate(**args)


# ---- 설정
def test_no_key_means_no_key_state_and_server_works(make_client):
    client = make_client(llm=None)
    status = client.get("/api/ai/status").json()
    assert status["state"] == "no_key"
    assert status["key_present"] is False
    assert client.get("/api/health").status_code == 200


def test_fake_llm_means_ready(make_client):
    client = make_client(llm=FakeLLM())
    assert client.get("/api/ai/status").json()["state"] == "ready"


def test_ai_enabled_false_turns_it_off_even_with_key(make_client, monkeypatch):
    monkeypatch.setenv("AI_ENABLED", "false")
    client = make_client(llm=FakeLLM())
    assert client.get("/api/ai/status").json()["state"] == "off"


def test_bad_numbers_only_disable_nothing_and_are_reported():
    settings = config.get_ai_settings({"AI_MAX_RETRIES": "abc", "AI_MONTHLY_CALL_LIMIT": "0", "AI_ENABLED": "maybe"})
    assert settings.max_retries == 1 and settings.monthly_call_limit == 300 and settings.enabled is True
    assert len(settings.problems) == 3


def test_defaults_need_only_the_key():
    settings = config.get_ai_settings({})
    assert (settings.enabled, settings.model, settings.max_retries, settings.monthly_call_limit) == (True, "", 1, 300)


def test_env_file_key_is_picked_up_without_restart(tmp_path, session_factory, monkeypatch):
    env_file = tmp_path / ".env"
    service = AiService(session_factory, env_file=env_file)
    assert service.state() == "no_key"
    env_file.write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    assert service.state() == "ready"  # 서버를 다시 켜지 않아도 반영됩니다
    env_file.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    os.utime(env_file, (env_file.stat().st_atime, env_file.stat().st_mtime + 5))
    assert service.state() == "no_key"


def test_status_never_contains_the_key(tmp_path, session_factory):
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    service = AiService(session_factory, env_file=env_file)
    assert SECRET not in str(service.status())
    assert SECRET not in repr(service)


# ---- 월 한도
def test_month_boundary_uses_korean_time():
    assert month_start_utc(datetime(2026, 2, 28, 15, 0)) == datetime(2026, 2, 28, 15, 0)  # 한국 3/1 00:00
    assert month_start_utc(datetime(2026, 2, 28, 14, 59)) == datetime(2026, 1, 31, 15, 0)  # 한국 2/28 23:59
    assert month_start_utc(datetime(2026, 3, 10, 3, 0)) == datetime(2026, 2, 28, 15, 0)


def test_monthly_limit_stops_calls(session_factory):
    llm = FakeLLM(default={"ok": True})
    service = AiService(session_factory, llm=llm, settings=config.AiSettings(monthly_call_limit=2, max_retries=0))
    call(service)
    call(service)
    assert service.state() == "limit"
    with pytest.raises(AiError) as error:
        call(service)
    assert error.value.code == "limit"
    assert len(llm.calls) == 2  # 한도 뒤에는 호출하지 않음


def test_retries_count_toward_the_limit(session_factory):
    llm = FakeLLM(responses=[AiError("timeout"), {"ok": True}])
    service = AiService(session_factory, llm=llm, settings=config.AiSettings(monthly_call_limit=10, max_retries=1))
    call(service)
    assert len(llm.calls) == 2
    assert service.month_used() == 2


def test_limit_resets_next_month(session_factory):
    now = {"t": datetime(2026, 2, 20, 12, 0)}
    llm = FakeLLM(default={"ok": True})
    service = AiService(session_factory, llm=llm, settings=config.AiSettings(monthly_call_limit=1, max_retries=0), clock=lambda: now["t"])
    call(service)
    assert service.state() == "limit"
    now["t"] = datetime(2026, 3, 5, 12, 0)
    assert service.state() == "ready"


# ---- 서킷 브레이커와 인증 오류
def test_three_failures_open_the_circuit_for_ten_minutes(session_factory):
    now = {"t": datetime(2026, 2, 20, 12, 0)}
    llm = FakeLLM(default=AiError("server"))
    service = AiService(session_factory, llm=llm, settings=config.AiSettings(max_retries=0, monthly_call_limit=100), clock=lambda: now["t"])
    for _ in range(3):
        with pytest.raises(AiError):
            call(service)
    assert service.state() == "degraded"
    with pytest.raises(AiError):
        call(service)
    assert len(llm.calls) == 3  # 잠시 멈춘 동안은 호출하지 않음
    now["t"] += timedelta(minutes=11)
    assert service.state() == "ready"


def test_success_resets_failure_count(session_factory):
    llm = FakeLLM(responses=[AiError("server"), AiError("server"), {"ok": True}, AiError("server"), AiError("server")])
    service = AiService(session_factory, llm=llm, settings=config.AiSettings(max_retries=0, monthly_call_limit=100))
    for expected in (AiError, AiError, None, AiError, AiError):
        if expected:
            with pytest.raises(AiError):
                call(service)
        else:
            call(service)
    assert service.state() == "ready"


def test_auth_error_is_not_retried_and_marks_key_invalid(tmp_path, session_factory, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"OPENAI_API_KEY={SECRET}\n", encoding="utf-8")
    llm = FakeLLM(default=AiError("auth"))
    monkeypatch.setattr(service_module, "OpenAILLM", lambda *args, **kwargs: llm)
    service = AiService(session_factory, env_file=env_file, settings=config.AiSettings(max_retries=2, monthly_call_limit=100))
    with pytest.raises(AiError) as error:
        call(service)
    assert error.value.code == "auth"
    assert len(llm.calls) == 1  # 재시도 없음
    assert service.state() == "key_invalid"
    # 키를 바꾸면 다시 시도할 수 있습니다.
    env_file.write_text("OPENAI_API_KEY=sk-test-NEW-key-0000000000\n", encoding="utf-8")
    os.utime(env_file, (env_file.stat().st_atime, env_file.stat().st_mtime + 5))
    assert service.state() == "ready"


def test_unknown_exception_becomes_ai_error_not_a_crash(session_factory):
    llm = FakeLLM(default=RuntimeError("boom with details"))
    service = AiService(session_factory, llm=llm, settings=config.AiSettings(max_retries=0, monthly_call_limit=100))
    with pytest.raises(AiError) as error:
        call(service)
    assert error.value.code == "server"
    assert "boom" not in str(error.value)


def test_usage_rows_store_no_prompt_or_answer(session_factory):
    from sqlalchemy import select

    from app.models import AiUsage

    llm = FakeLLM(default={"secret_answer": "내용"})
    service = AiService(session_factory, llm=llm, settings=config.AiSettings(max_retries=0, monthly_call_limit=100))
    call(service, user="점주가 쓴 비밀 문장")
    with session_factory() as db:
        row = db.scalar(select(AiUsage))
    dumped = " ".join(str(v) for v in vars(row).values())
    assert "비밀 문장" not in dumped and "내용" not in dumped
    assert (row.ok, row.input_tokens, row.output_tokens, row.kind) == (True, 120, 60, "briefing")
