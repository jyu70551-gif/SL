import { useEffect, useState } from "react";
import { ApiError } from "../api.js";
import { useAuth } from "../auth.jsx";

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

export default function Login() {
  const { login } = useAuth();
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [lockedSeconds, setLockedSeconds] = useState(0);
  const [busy, setBusy] = useState(false);

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

  return (
    <main className="login">
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
