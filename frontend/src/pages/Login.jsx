import { useEffect, useState } from "react";
import { ApiError, request } from "../api.js";
import { useAuth } from "../auth.jsx";
import StoreScene from "../components/StoreScene.jsx";

function messageFor(error) {
  if (!(error instanceof ApiError)) return "문제가 생겼어요. 잠시 후 다시 시도해 주세요.";
  const { code, remaining_attempts: remaining } = error.detail;
  if (code === "wrong_password") {
    return `비밀번호가 맞지 않습니다. (남은 시도 ${remaining}번)`;
  }
  if (code === "not_configured") {
    return "비밀번호가 아직 정해지지 않았어요. 서버 설정(.env)을 확인해 주세요.";
  }
  if (code === "network") return "서버에 연결할 수 없어요.";
  return "문제가 생겼어요. 잠시 후 다시 시도해 주세요.";
}

const MIN_PASSWORD_LENGTH = 8;

function setupMessage(error) {
  if (!(error instanceof ApiError)) return "문제가 생겼어요. 잠시 후 다시 시도해 주세요.";
  const code = error.detail.code;
  if (code === "password_too_short") return `비밀번호는 ${MIN_PASSWORD_LENGTH}글자 이상으로 만들어 주세요.`;
  if (code === "already_configured") return "이미 비밀번호가 만들어져 있어요. 새로고침해서 로그인해 주세요.";
  if (code === "network") return "서버에 연결할 수 없어요.";
  return "문제가 생겼어요. 잠시 후 다시 시도해 주세요.";
}

// 비밀번호가 아직 없을 때(처음 쓸 때)만 보이는 "비밀번호 만들기" 화면
function CreatePassword({ onDone }) {
  const { setup } = useAuth();
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    if (password.length < MIN_PASSWORD_LENGTH) {
      setMessage(`비밀번호는 ${MIN_PASSWORD_LENGTH}글자 이상으로 만들어 주세요.`);
      return;
    }
    if (password !== again) {
      setMessage("두 번 입력한 비밀번호가 서로 달라요.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await setup(password);
    } catch (error) {
      setMessage(setupMessage(error));
      if (error instanceof ApiError && error.detail.code === "already_configured") onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <StoreScene />
      <h1 className="login-title">SL</h1>
      <form onSubmit={submit} className="login-form">
        <p className="muted">처음 쓰시네요. 사용할 비밀번호를 만들어 주세요. ({MIN_PASSWORD_LENGTH}글자 이상)</p>
        <label htmlFor="new-password">새 비밀번호</label>
        <input id="new-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        <label htmlFor="new-password-again">비밀번호 한 번 더</label>
        <input id="new-password-again" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
        <button type="submit" className="button" disabled={busy || !password || !again}>
          비밀번호 만들고 들어가기
        </button>
        {message && (
          <p className="error" role="alert">
            {message}
          </p>
        )}
      </form>
    </main>
  );
}

export default function Login() {
  const { login } = useAuth();
  const [configured, setConfigured] = useState(true); // 서버가 "비밀번호 없음"이라고 알려 줄 때만 만들기 화면으로 바꿉니다
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [lockedSeconds, setLockedSeconds] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request("/api/auth/status")
      .then((body) => setConfigured(body.configured !== false))
      .catch(() => {}); // 확인하지 못하면 평소 로그인 화면 그대로
  }, []);

  useEffect(() => {
    if (lockedSeconds <= 0) return undefined;
    const timer = setInterval(() => setLockedSeconds((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [lockedSeconds > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(event) {
    event.preventDefault();
    if (busy || lockedSeconds > 0 || !password) return;
    setBusy(true);
    setMessage("");
    try {
      await login(password);
    } catch (error) {
      if (error instanceof ApiError && error.detail.code === "locked") {
        setLockedSeconds(error.detail.retry_after_seconds);
        setMessage("");
      } else {
        setMessage(messageFor(error));
      }
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  const minutes = Math.ceil(lockedSeconds / 60);

  if (!configured) return <CreatePassword onDone={() => setConfigured(true)} />;

  return (
    <main className="login">
      <StoreScene />
      <h1 className="login-title">SL</h1>
      <form onSubmit={submit} className="login-form">
        <label htmlFor="password">비밀번호</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={lockedSeconds > 0}
          autoFocus
        />
        <button type="submit" className="button" disabled={busy || lockedSeconds > 0 || !password}>
          들어가기
        </button>
        {lockedSeconds > 0 && (
          <p className="error" role="alert">
            잠시 후 다시 시도해 주세요. (약 {minutes}분 뒤)
          </p>
        )}
        {message && (
          <p className="error" role="alert">
            {message}
          </p>
        )}
      </form>
    </main>
  );
}
