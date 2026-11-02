"""OpenAI 호출을 한 곳에 모은 클라이언트 (SDD 6.4).

- 호출 방식(Responses API, JSON 스키마 응답)은 이 파일 안에만 있습니다. 나머지 코드는 `LLM` 인터페이스만 압니다.
- 키는 객체를 만들 때 한 번만 넘기고, `repr`, 로그, 예외 메시지에 넣지 않습니다.
- 한 번의 호출은 한 번만 시도합니다(SDK 자동 재시도 끔). 재시도와 횟수 계산은 `AiService`가 합니다.
"""
import json
from dataclasses import dataclass
from typing import Protocol

from app.config import AI_MODEL_CANDIDATES

RETRYABLE = {"timeout", "rate_limit", "server", "connection", "invalid"}


class AiError(Exception):
    """AI 호출이나 사용 가능 여부의 문제. code 는 화면·기록에 쓰는 짧은 종류 이름입니다."""

    def __init__(self, code: str, hint: str = ""):
        super().__init__(code)
        self.code = code
        self.hint = hint  # 점주가 고칠 수 있는 안내(키·모델 이름 등은 담지 않음)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE


@dataclass
class LLMResult:
    data: dict
    input_tokens: int | None
    output_tokens: int | None
    model: str


class LLM(Protocol):
    model_name: str

    def generate_json(
        self, *, system: str, user: str, schema_name: str, schema: dict, max_output_tokens: int
    ) -> LLMResult: ...


class OpenAILLM:
    """실제 OpenAI 호출. 키가 바뀌면 AiService 가 새 객체를 만듭니다."""

    def __init__(self, api_key: str, model: str = "", timeout: float = 20.0):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)
        self._configured_model = model.strip()
        self._resolved: str = self._configured_model

    def __repr__(self) -> str:  # 키가 어디에도 찍히지 않게
        return f"OpenAILLM(model={self.model_name!r})"

    @property
    def model_name(self) -> str:
        return self._resolved or "(자동 선택 전)"

    # --- 모델 고르기 -------------------------------------------------
    def _resolve_model(self) -> str:
        if self._resolved:
            return self._resolved
        available: set[str] = set()
        try:
            for item in self._client.models.list():
                available.add(item.id)
        except Exception as error:  # noqa: BLE001 - 아래에서 종류별로 바꿉니다
            raise self._map_error(error) from None
        for candidate in AI_MODEL_CANDIDATES:
            if candidate in available:
                self._resolved = candidate
                return candidate
        raise AiError(
            "no_model",
            "이 키로 쓸 수 있는 모델을 찾지 못했어요. backend/.env 의 OPENAI_MODEL 에 쓸 모델 이름을 직접 적어 주세요.",
        )

    # --- 호출 --------------------------------------------------------
    def generate_json(
        self, *, system: str, user: str, schema_name: str, schema: dict, max_output_tokens: int
    ) -> LLMResult:
        model = self._resolve_model()
        try:
            response = self._client.responses.create(
                model=model,
                instructions=system,
                input=user,
                text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
                max_output_tokens=max_output_tokens,
                store=False,  # OpenAI 쪽에 응답을 저장해 두지 않습니다
            )
        except Exception as error:  # noqa: BLE001
            raise self._map_error(error) from None

        if getattr(response, "status", "completed") == "incomplete":
            raise AiError("invalid", "응답이 끝까지 만들어지지 않았어요.")
        text = getattr(response, "output_text", "") or ""
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            raise AiError("invalid", "응답이 약속된 형식이 아니에요.") from None
        if not isinstance(data, dict):
            raise AiError("invalid", "응답이 약속된 형식이 아니에요.")

        usage = getattr(response, "usage", None)
        return LLMResult(
            data=data,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            model=model,
        )

    # --- 오류 이름 바꾸기 (원문 메시지는 버립니다. 키나 입력이 섞일 수 있어서) -------
    @staticmethod
    def _map_error(error: Exception) -> AiError:
        import openai

        if isinstance(error, openai.AuthenticationError):
            return AiError("auth", "OpenAI 키가 올바르지 않아요. backend/.env 의 OPENAI_API_KEY 를 확인해 주세요.")
        if isinstance(error, openai.PermissionDeniedError):
            return AiError("auth", "이 키에는 사용 권한이 없어요. OpenAI 계정과 키의 권한을 확인해 주세요.")
        if isinstance(error, openai.NotFoundError):
            return AiError("model", "모델 이름을 찾을 수 없어요. backend/.env 의 OPENAI_MODEL 을 확인하거나 비워 두세요.")
        if isinstance(error, openai.RateLimitError):
            return AiError("rate_limit", "OpenAI 사용 한도에 걸렸어요. 잔액이나 한도를 확인해 주세요.")
        if isinstance(error, openai.APITimeoutError):
            return AiError("timeout", "응답이 늦어서 중단했어요.")
        if isinstance(error, openai.APIConnectionError):
            return AiError("connection", "OpenAI에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")
        if isinstance(error, openai.BadRequestError):
            return AiError("request", "요청 형식이 맞지 않았어요.")
        if isinstance(error, openai.APIStatusError):
            return AiError("server", "OpenAI 서버에 문제가 있어요.")
        return AiError("server", "알 수 없는 문제가 생겼어요.")
