"""비밀번호를 잊어버렸을 때 다시 정하는 도구 (spec 7-2).

사용법 (backend 폴더에서):
    python set_password.py

새 비밀번호를 두 번 입력하면 저장하고, 잠금과 기존 로그인을 모두 초기화합니다.
"""
import getpass
import sys

from sqlalchemy import delete

from app.config import MIN_PASSWORD_LENGTH, get_settings
from app.db import Base, make_engine, make_session_factory
from app.models import AuthSession, AuthState
from app.security import hash_password


def main() -> int:
    first = getpass.getpass("새 비밀번호: ")
    if len(first) < MIN_PASSWORD_LENGTH:
        print(f"비밀번호는 {MIN_PASSWORD_LENGTH}글자 이상이어야 합니다.")
        return 1
    if getpass.getpass("새 비밀번호 한 번 더: ") != first:
        print("두 번 입력한 비밀번호가 서로 다릅니다.")
        return 1

    engine = make_engine(get_settings().database_url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as db:
        state = db.get(AuthState, 1)
        if state is None:
            state = AuthState(id=1, password_hash=hash_password(first))
            db.add(state)
        else:
            state.password_hash = hash_password(first)
            state.failed_count = 0
            state.locked_until = None
        db.execute(delete(AuthSession))
        db.commit()
    print("비밀번호를 바꿨습니다. 모든 기기에서 다시 로그인해야 합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
