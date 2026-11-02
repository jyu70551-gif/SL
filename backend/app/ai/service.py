"""AI 사용 가능 상태, 월 사용 한도, 서킷 브레이커 (SDD 4장, 6.9).

상태: off(AI_ENABLED=false) / no_key / key_invalid / limit(월 한도) / degraded(연속 실패) / ready
READY 가 아니면 모든 AI 기능은 고정 문구 모드로 동작합니다.
"""
import hashlib
import threading
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app import config
from app.ai.client import AiError, LLM, LLMResult, OpenAILLM
from app.models import AiUsage

KST_OFFSET = timedelta(hours=9)  # 한국은 서머타임이 없어 고정 오프셋으로 충분합니다
CIRCUIT_FAILURES = 3
CIRCUIT_OPEN = timedelta(minutes=10)


def month_start_utc(now_utc: datetime) -> datetime:
    """한국 시간 기준 이번 달 1일 0시를 UTC(시간대 없는 값)로."""
    kst = now_utc + KST_OFFSET
    start_kst = kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start_kst - KST_OFFSET


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class AiService:
    def __init__(self, session_factory, llm: LLM | None = None, env_file: Path | None = None, settings=None, clock=None):
        self._session_factory = session_factory
        self._injected = llm  # 시험에서 가짜 LLM 을 넣습니다
        self._env_file = env_file
        self._settings_override = settings
        self._clock = clock or config_utcnow
        self._real: OpenAILLM | None = None
        self._real_signature: tuple | None = None
        self._lock = threading.Lock()
        self._fail_count = 0
        self._open_until: datetime | None = None
        self._bad_key: str | None = None  # 인증 오류가 난 키의 지문
        self._last_error = ""

    # ------------------------------------------------------------------ 설정·키
    def settings(self):
        return self._settings_override or config.read_ai_settings(self._env_file)

    def _key(self) -> str:
        return config.read_openai_key(self._env_file)

    def key_present(self) -> bool:
        return self._injected is not None or bool(self._key())

    def _llm(self) -> LLM | None:
        if self._injected is not None:
            return self._injected
        key = self._key()
        if not key:
            return None
        settings = self.settings()
        signature = (_fingerprint(key), settings.model, settings.timeout_seconds)
        if self._real is None or self._real_signature != signature:
            self._real = OpenAILLM(key, settings.model, settings.timeout_seconds)
            self._real_signature = signature
        return self._real

    # ------------------------------------------------------------------ 사용량
    def month_used(self) -> int:
        with self._session_factory() as db:
            return int(
                db.scalar(select(func.count()).select_from(AiUsage).where(AiUsage.created_at >= month_start_utc(self._clock())))
                or 0
            )

    # ------------------------------------------------------------------ 상태
    def state(self) -> str:
        settings = self.settings()
        if not settings.enabled:
            return "off"
        if not self.key_present():
            return "no_key"
        if self._injected is None and self._bad_key == _fingerprint(self._key()):
            return "key_invalid"
        if self.month_used() >= settings.monthly_call_limit:
            return "limit"
        if self._open_until is not None and self._clock() < self._open_until:
            return "degraded"
        return "ready"

    def is_ready(self) -> bool:
        return self.state() == "ready"

    def status(self) -> dict:
        """화면과 `GET /api/ai/status`에 내보내는 요약. 키 값은 절대 넣지 않습니다."""
        settings = self.settings()
        llm = self._injected or self._real
        return {
            "enabled": settings.enabled,
            "key_present": self.key_present(),
            "state": self.state(),
            "model": getattr(llm, "model_name", "") if llm is not None else (settings.model or "(자동 선택)"),
            "month_used": self.month_used(),
            "month_limit": settings.monthly_call_limit,
            "last_error": self._last_error,
            "problems": list(settings.problems),
        }

    # ------------------------------------------------------------------ 호출
    def _reserve(self, kind: str, model: str, limit: int) -> int:
        """호출 직전에 사용 기록을 먼저 남겨, 동시에 불러도 한도를 넘지 않게 합니다."""
        with self._lock:
            used = self.month_used()
            if used >= limit:
                raise AiError("limit")
            with self._session_factory() as db:
                row = AiUsage(created_at=self._clock(), kind=kind, model=model, ok=False, error="pending")
                db.add(row)
                db.commit()
                return row.id

    def _finish(self, usage_id: int, *, ok: bool, error: str = "", result: LLMResult | None = None) -> None:
        with self._session_factory() as db:
            row = db.get(AiUsage, usage_id)
            if row is None:
                return
            row.ok = ok
            row.error = error[:40]
            if result is not None:
                row.model = result.model[:64]
                row.input_tokens = result.input_tokens
                row.output_tokens = result.output_tokens
            db.commit()

    def generate(self, *, kind: str, system: str, user: str, schema_name: str, schema: dict, max_output_tokens: int) -> LLMResult:
        """AI 호출 한 건(필요하면 재시도 포함). 실패는 AiError 로만 알립니다."""
        state = self.state()
        if state != "ready":
            raise AiError(state)
        llm = self._llm()
        if llm is None:
            raise AiError("no_key")
        settings = self.settings()
        attempts = 1 + settings.max_retries
        for attempt in range(attempts):
            usage_id = self._reserve(kind, getattr(llm, "model_name", ""), settings.monthly_call_limit)
            try:
                result = llm.generate_json(
                    system=system, user=user, schema_name=schema_name, schema=schema, max_output_tokens=max_output_tokens
                )
            except AiError as error:
                self._finish(usage_id, ok=False, error=error.code)
                self._last_error = error.code
                if error.code == "auth":
                    self._bad_key = _fingerprint(self._key())  # 같은 키로는 다시 부르지 않습니다
                    raise
                if error.retryable and attempt < attempts - 1:
                    continue
                self._record_failure()
                raise
            except Exception:  # noqa: BLE001 - 알 수 없는 예외도 고정 문구로 떨어지게 합니다
                self._finish(usage_id, ok=False, error="unknown")
                self._last_error = "unknown"
                self._record_failure()
                raise AiError("server") from None
            self._finish(usage_id, ok=True, result=result)
            self._fail_count = 0
            self._open_until = None
            self._last_error = ""
            return result
        raise AiError("server")  # 도달하지 않음

    def record_guard_failure(self) -> None:
        """가드(검증)에서 막힌 응답도 실패로 셉니다. 계속 막히면 잠시 호출을 멈춥니다."""
        self._last_error = "guard"
        self._record_failure()

    def _record_failure(self) -> None:
        self._fail_count += 1
        if self._fail_count >= CIRCUIT_FAILURES:
            self._open_until = self._clock() + CIRCUIT_OPEN
            self._fail_count = 0


def config_utcnow() -> datetime:
    from app.auth import utcnow

    return utcnow()
