"""DB 연결 점검 도구. 설정을 읽고 Supabase에 연결해 보기만 합니다. (데이터는 바꾸지 않습니다)

사용법 (backend 폴더에서):
    python check_db.py

결과로 '무엇이 잘못됐는지'와 '확인할 항목'만 알려줍니다. 비밀번호나 접속 주소는 출력하지 않습니다.
"""
import sys

from app.config import DbConfigError, build_database_url
from app.db import DbConnectionError, make_engine, verify_connection
from sqlalchemy import inspect


def main() -> int:
    try:
        url = build_database_url()
    except DbConfigError as error:
        print(error)
        return 1

    engine = make_engine(url)
    try:
        verify_connection(engine)
    except DbConnectionError as error:
        print(error)
        return 1

    print("DB에 연결됐어요. (접속 정보는 올바릅니다)")
    if inspect(engine).has_table("auth_state"):
        print("테이블이 이미 준비되어 있어요. 서버를 켜면 됩니다.")
    else:
        print("테이블은 아직 없어요. 'python -m alembic upgrade head' 를 실행해 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
