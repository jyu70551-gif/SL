"""OpenAI 키가 제대로 연결됐는지 확인합니다. (키를 넣은 뒤 한 번 실행하세요)

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe check_ai.py

- backend/.env 의 OPENAI_API_KEY 로 아주 작은 호출을 딱 한 번 합니다. (비용은 거의 없습니다)
- 키 값은 화면에 출력하지 않습니다.
- 데이터베이스는 건드리지 않습니다.
"""
import sys

from app import config
from app.ai.client import AiError, OpenAILLM


def main() -> int:
    settings = config.read_ai_settings(config.AI_ENV_FILE)
    for problem in settings.problems:
        print(f"[주의] {problem}")
    if not settings.enabled:
        print("AI_ENABLED=false 라서 AI 기능이 꺼져 있어요. 켜려면 backend/.env 에서 이 줄을 지우거나 true 로 바꿔 주세요.")
        return 1

    key = config.read_openai_key(config.AI_ENV_FILE)
    if not key:
        print("OPENAI_API_KEY 가 비어 있어요.")
        print("backend/.env 파일에 아래 한 줄을 넣고 다시 실행해 주세요. (키는 채팅이나 문서에 적지 마세요)")
        print("    OPENAI_API_KEY=여기에_발급받은_키")
        return 1

    print("키를 찾았어요. OpenAI에 작은 확인 요청을 한 번 보냅니다...")
    llm = OpenAILLM(key, settings.model, settings.timeout_seconds)
    try:
        result = llm.generate_json(
            system="요청에 맞는 JSON만 돌려줍니다.",
            user='{"check": true} 를 받으면 ok 를 true 로 해서 돌려주세요.',
            schema_name="check",
            schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
            max_output_tokens=200,
        )
    except AiError as error:
        print(f"연결에 실패했어요 ({error.code}).")
        if error.hint:
            print(f"  → {error.hint}")
        return 1

    print("연결됐어요!")
    print(f"  사용할 모델: {result.model}")
    print(f"  사용한 토큰: 입력 {result.input_tokens}, 출력 {result.output_tokens}")
    print("서버를 다시 켜지 않아도 됩니다. 매출 파일을 올리거나 홈을 열면 AI 점검이 만들어져요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
