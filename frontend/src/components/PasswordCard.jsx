import { useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

const ERROR_TEXT = {
  wrong_password: "현재 비밀번호가 맞지 않아요.",
  mismatch: "새 비밀번호 두 개가 서로 달라요.",
  too_short: "새 비밀번호는 8글자 이상이어야 해요.",
};

export default function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // { kind, text }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await request("/api/settings/password", { method: "POST", body: { current, new: next, new_again: again } });
      setCurrent("");
      setNext("");
      setAgain("");
      setMessage({ kind: "ok", text: "비밀번호를 바꿨어요. 다음에 들어올 때부터 새 비밀번호를 입력해 주세요." });
    } catch (e) {
      setMessage({ kind: "error", text: ERROR_TEXT[e.detail?.code] ?? "바꾸지 못했어요. 잠시 뒤 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="비밀번호 바꾸기">
      <form className="settings-form" onSubmit={submit}>
        <label htmlFor="pw-current">현재 비밀번호</label>
        <input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <label htmlFor="pw-new">새 비밀번호 (8글자 이상)</label>
        <input id="pw-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        <label htmlFor="pw-again">새 비밀번호 다시 입력</label>
        <input id="pw-again" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
        <button type="submit" className="button" disabled={busy || !current || !next || !again}>
          바꾸기
        </button>
        {message?.kind === "ok" && <p className="settings-saved">{message.text}</p>}
        {message?.kind === "error" && (
          <p className="error" role="alert">
            {message.text}
          </p>
        )}
      </form>
      <p className="card-note">바꾸면 다른 기기에서는 로그아웃돼요. 비밀번호를 잊으면 화면에서 되찾을 수 없고, 서버 설정을 직접 고쳐야 해요.</p>
    </Card>
  );
}
