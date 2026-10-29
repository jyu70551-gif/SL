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

- 개발 중에는 `backend/sl_dev.db`(SQLite) 파일에 저장됩니다. 지우면 처음 상태로 돌아갑니다.
- `backend/.env`의 `DATABASE_URL` 한 줄로 Supabase로 바꿉니다. (Phase 2에서 연결합니다)
