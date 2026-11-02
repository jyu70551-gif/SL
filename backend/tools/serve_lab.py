"""랩 DB로 서버를 켭니다 (docs/lab.md). 실제 Supabase에는 연결하지 않습니다.

- 화면 맨 위에 "시연용 가짜 데이터" 표시가 뜹니다.
- AI는 backend/.env 의 OpenAI 키를 그대로 씁니다. (호출 기록과 월 한도는 랩 DB에 따로 쌓이지만, OpenAI 요금은 같은 계정에 붙습니다)
- 로그인은 시연용이라 비밀번호에 아무거나 넣어도 됩니다. (잠금도 무시. 이 도구로 켠 랩 서버에서만 그렇습니다)

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\serve_lab.py                  (포트 8100)
    그다음 다른 터미널에서 화면:
    cd ..\\frontend ; $env:VITE_PROXY_TARGET="http://127.0.0.1:8100" ; npm.cmd run dev -- --port 5180
    브라우저에서 http://localhost:5180
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DEFAULT_DB = BACKEND / "lab" / "lab.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="랩 DB로 서버 켜기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="랩 DB 파일 (.db)")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    if args.db.suffix != ".db" or not args.db.exists():
        raise SystemExit(f"랩 DB를 찾지 못했어요: {args.db}\n먼저 tools/make_lab_data.py 를 실행해 주세요.")

    os.environ["SL_LAB_MODE"] = "1"  # 화면에 "시연용 가짜 데이터" 표시
    import uvicorn

    from app.db import Base, make_engine
    from app.main import create_app

    # 예전에 만든 랩 DB에 나중에 추가된 테이블(예: 설정)이 없을 수 있어서 SQLite 파일에 한해 빠진 테이블만 만듭니다.
    engine = make_engine(f"sqlite:///{args.db}")
    Base.metadata.create_all(engine)
    engine.dispose()

    # 일부러 SQLite 파일 주소만 넘깁니다. backend/.env 의 DB_* (Supabase) 값은 쓰이지 않습니다.
    app = create_app(database_url=f"sqlite:///{args.db}")
    app.state.open_login = True  # 시연용: 비밀번호 아무거나로 로그인됩니다. 이 도구에서만 켜지고, 일반 서버에는 없는 설정입니다.
    print(f"랩 서버를 켭니다: http://127.0.0.1:{args.port}  (DB: {args.db.name}, 실제 DB 아님)")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
