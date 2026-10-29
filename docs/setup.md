# 내 컴퓨터에서 SL 실행하기

> 개발 중인 SL을 내 컴퓨터에서 켜 보는 방법입니다. (Phase 1 기준)
> PowerShell 창을 **두 개** 열어서 하나는 서버, 하나는 화면을 켭니다.

---

## 처음 한 번만 하기

### 1. 비밀번호 정하기

1. `backend` 폴더에서 `.env.example` 파일을 복사해서 이름을 **`.env`** 로 바꿉니다.
2. `.env` 파일을 열어 `INITIAL_PASSWORD=` 뒤에 **8글자 이상**의 비밀번호를 적습니다.
3. 저장합니다.

> `.env`는 깃에 올라가지 않습니다. 비밀번호를 채팅이나 문서에 적지 마세요.
> 이 비밀번호는 **서버가 처음 켜질 때 한 번만** 읽혀서 암호화되어 저장됩니다. 이후 `.env`의 값을 바꿔도 비밀번호는 바뀌지 않습니다. (바꾸는 방법은 아래 참고)

### 2. 서버 준비하기 (이미 되어 있습니다)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### 3. 화면 준비하기 (이미 되어 있습니다)

```powershell
cd frontend
npm.cmd install
```

---

## Supabase(데이터 보관함) 연결하기

데이터는 Supabase(PostgreSQL)에 저장합니다. 서버는 **SQLite로 자동 연결하지 않습니다.** 아래 값이 없거나 틀리면 이유를 알려 주고 멈춥니다.

### 1. `backend/.env`에 연결 정보 입력

Supabase 대시보드 → 프로젝트 선택 → 위쪽 **Connect** 버튼 → **Session pooler** 항목을 보면서 아래 다섯 칸을 채웁니다. 값만 적고, 따옴표나 `postgresql://`는 넣지 않습니다.

| 항목 | 넣을 값 |
|---|---|
| `DB_HOST` | Session pooler의 주소 (예: `aws-0-ap-northeast-2.pooler.supabase.com`, 프로젝트마다 다름) |
| `DB_PORT` | `5432` |
| `DB_NAME` | `postgres` |
| `DB_USER` | `postgres.프로젝트ID` 형태 (그냥 `postgres`가 아님) |
| `DB_PASSWORD` | 프로젝트를 만들 때 정한 **데이터베이스 비밀번호** (SL 비밀번호나 Supabase 계정 비밀번호가 아님) |

> 예전 `.env`에 있던 `DATABASE_URL` 줄은 더 이상 쓰이지 않습니다. 지워도 됩니다.
> 비밀번호는 채팅에 적지 말고 `.env`에만 넣으세요. `.env`는 깃에 올라가지 않습니다.

### 2. 연결이 되는지 먼저 점검하기 (선택)

```powershell
cd C:\Users\aicam\Desktop\SL\backend
.\.venv\Scripts\python.exe check_db.py
```

"DB에 연결됐어요"가 나오면 접속 정보가 맞는 것입니다. 틀렸다면 무엇을 확인해야 하는지 알려 줍니다. (데이터는 바꾸지 않습니다)

### 3. 테이블 만들기 (명령 하나)

```powershell
cd C:\Users\aicam\Desktop\SL\backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

- 필요한 테이블(비밀번호, 로그인 기록, 올린 파일, 대분류별 매출, **확인함·정상 기록**)이 만들어집니다.
- **새 기능이 추가되어 테이블이 늘면 이 명령을 한 번 더 실행하고 서버를 다시 켜야 합니다.** 안 하면 서버가 "필요한 테이블이 아직 없어요"라고 알려 주며 켜지지 않습니다. (Phase 4에서 운영 상황 기록 테이블이 추가되었고, 이어서 선택 항목·메모를 저장하는 열 2개가 추가되었습니다)
- **이미 적용한 변경은 다시 적용되지 않습니다.** 같은 명령을 여러 번 실행해도 안전합니다.
- 중간에 실패하면 아무것도 적용되지 않습니다.
- 연결 없이 만들어질 SQL만 보고 싶으면 명령 끝에 `--sql`을 붙입니다.

### 4. 서버를 다시 켜서 확인하기

1. 켜져 있는 서버 창에서 `Ctrl + C`로 끕니다.
2. 서버를 다시 켭니다. (아래 "매번 켜는 방법")
3. 브라우저에서 http://localhost:5173 을 열어 `.env`의 `INITIAL_PASSWORD` 비밀번호로 들어갑니다. (처음 켤 때 새 데이터 보관함에 이 비밀번호가 저장됩니다)
4. **파일 올리기** 화면에서 `backend/tests/fixtures/sample_2026-02-25.csv`를 올립니다.
5. 올려 둔 날짜 목록에 날짜가 보이면 Supabase에 저장된 것입니다. Supabase 대시보드의 **Table Editor**에서도 `sales_uploads`, `daily_sales` 표를 볼 수 있습니다.

> 이 프로젝트에는 회원가입이 없습니다. 비밀번호 로그인과 파일 올리기로 확인합니다.
> 예전 SQLite 데이터(`backend/sl_dev.db`)는 그대로 남아 있지만 더 이상 쓰이지 않고, 새 데이터부터 Supabase에 저장됩니다.

---

## 매번 켜는 방법

**창 1 — 서버**

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8000
```

**창 2 — 화면**

```powershell
cd frontend
npm.cmd run dev
```

> `npm`이 "스크립트를 실행할 수 없습니다"라고 하면 `npm.cmd`로 쓰면 됩니다. (아래 "자주 만나는 문제" 참고)

그다음 브라우저에서 **http://localhost:5173** 을 엽니다. 비밀번호 화면이 나옵니다.

끄려면 각 창에서 `Ctrl + C` 를 누릅니다.

---

## 새 기능이 보이지 않을 때

서버는 **켤 때 읽은 코드로 계속 동작**합니다. 코드가 바뀐 뒤에는 서버 창에서 `Ctrl + C`로 끄고 다시 켜야 새 기능이 반영됩니다. (화면은 자동으로 새로 고쳐집니다)

## 파일 올리기를 시험해 보고 싶을 때

`backend/tests/fixtures/` 폴더에 2월 24일·25일 날짜의 시험용 CSV(숫자는 가상)가 있습니다. **파일 올리기** 화면에서 이 파일을 골라 시각을 선택하고 올려 보세요. 같은 파일을 한 번 더 올리면 덮어쓰기 확인 창이 나옵니다.

---

## 자주 만나는 문제

### `npm : 이 시스템에서 스크립트를 실행할 수 없으므로 ... npm.ps1` 오류

Windows PowerShell이 스크립트 실행을 막아 둔 설정 때문입니다. 아래 중 하나로 해결합니다.

- **간단한 방법:** `npm` 대신 **`npm.cmd`** 를 씁니다. (예: `npm.cmd run dev`, `npm.cmd install`)
- **설정을 바꾸는 방법:** 아래 명령을 한 번만 실행하면 이후에는 `npm`을 그대로 쓸 수 있습니다. (현재 사용자에게만 적용됩니다)
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  ```

### `[Errno 10048] ... 8000 ... 하나만 사용할 수 있습니다` 오류

서버가 **이미 켜져 있다**는 뜻입니다. 같은 서버를 한 번 더 켜면 나는 오류입니다.

- 이미 켜진 서버 창이 있으면 새로 켤 필요가 없습니다. 그 창을 그대로 두세요.
- 서버를 다시 켜고 싶으면 켜져 있는 창에서 `Ctrl + C`로 끈 뒤 다시 켭니다.
- 어느 창이 서버인지 모르겠으면 아래 명령으로 확인합니다.
  ```powershell
  Get-NetTCPConnection -LocalPort 8000 -State Listen
  ```

### `cd frontend` 가 `경로를 찾을 수 없습니다`로 나올 때

이미 `frontend` 폴더 안에 있다는 뜻입니다. 창 맨 앞의 경로(예: `PS C:\Users\aicam\Desktop\SL\frontend>`)를 확인하고, 이미 그 폴더라면 `cd`는 건너뛰고 `npm.cmd run dev`만 실행하세요.

---

## 시험(테스트) 돌리기

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

비밀번호 확인, 5번 틀리면 잠금, 30일 기억 등 Phase 1 확인 항목이 자동으로 검사됩니다. 시험에 쓰는 비밀번호는 가짜 값이라 실제 비밀번호와 무관합니다.

---

## 비밀번호를 잊어버렸거나 바꾸고 싶을 때

설정 화면의 비밀번호 바꾸기는 Phase 6에서 만듭니다. 그 전이나 잊어버렸을 때는 서버 창에서 이렇게 합니다.

```powershell
cd backend
.\.venv\Scripts\python.exe set_password.py
```

새 비밀번호를 두 번 입력하면 바뀌고, 잠금과 기존 로그인이 모두 초기화됩니다.

---

## 데이터 보관 위치

- 서비스의 데이터는 **Supabase(PostgreSQL)** 에 저장됩니다. (위 "Supabase 연결하기" 참고)
- `backend/sl_dev.db`(SQLite)는 예전 개발용 파일입니다. 지우지 않고 남겨 두었지만 서버가 사용하지 않습니다.
- 시험(`pytest`)은 임시 SQLite 파일에서만 돌고, 실제 Supabase에는 닿지 않습니다.
