import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

const ERROR_TEXT = {
  invalid_date: "날짜를 모두 올바르게 입력해 주세요.",
  end_before_start: "끝 날짜는 시작 날짜와 같거나 그 뒤여야 해요.",
};

function dateText(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

export default function VacationCard({ refreshKey = 0 }) {
  const [items, setItems] = useState(null);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [editing, setEditing] = useState(null); // 수정 중인 방학의 id
  const [message, setMessage] = useState(null); // { kind: "ok" | "error", text }
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    request("/api/settings/vacations")
      .then((r) => alive && setItems(r.items))
      .catch(() => alive && setMessage({ kind: "error", text: "방학 목록을 불러오지 못했어요." }));
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  function reset() {
    setStart("");
    setEnd("");
    setEditing(null);
  }

  async function call(path, method, body, okText) {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request(path, { method, body });
      setItems(r.items);
      setMessage({ kind: "ok", text: okText });
      return true;
    } catch (e) {
      setMessage({ kind: "error", text: ERROR_TEXT[e.detail?.code] ?? "저장하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    const body = { start_date: start, end_date: end };
    const ok = editing
      ? await call(`/api/settings/vacations/${editing}`, "PUT", body, "고쳤어요.")
      : await call("/api/settings/vacations", "POST", body, "추가했어요.");
    if (ok) reset();
  }

  async function remove(item) {
    if (!window.confirm(`${dateText(item.start_date)} ~ ${dateText(item.end_date)} 방학을 지울까요?`)) return;
    if (await call(`/api/settings/vacations/${item.id}`, "DELETE", undefined, "지웠어요.") && editing === item.id) reset();
  }

  function edit(item) {
    setEditing(item.id);
    setStart(item.start_date);
    setEnd(item.end_date);
    setMessage(null);
  }

  return (
    <Card title="방학 기간">
      {items === null && !message && <p className="card-note">불러오는 중…</p>}
      {items && items.length === 0 && <p className="card-note">아직 입력한 방학이 없어요.</p>}
      {items && items.length > 0 && (
        <ul className="vacation-list">
          {items.map((item) => (
            <li key={item.id}>
              <span>
                {item.source === "official" && (
                  <>
                    <strong>{item.name}</strong>
                    <span className="muted"> · 공식 학사일정</span>
                    <br />
                  </>
                )}
                {dateText(item.start_date)} ~ {dateText(item.end_date)}
              </span>
              <span className="vacation-actions">
                {item.source !== "official" && (
                  <button type="button" className="text-button" onClick={() => edit(item)} disabled={busy}>
                    수정
                  </button>
                )}
                <button type="button" className="text-button" onClick={() => remove(item)} disabled={busy}>
                  삭제
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <form className="settings-form" onSubmit={submit}>
        <label htmlFor="vacation-start">{editing ? "방학 시작 날짜 (수정 중)" : "방학 시작 날짜"}</label>
        <input id="vacation-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        <label htmlFor="vacation-end">방학 끝 날짜</label>
        <input id="vacation-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        <div className="button-row">
          <button type="submit" className="button" disabled={busy}>
            {editing ? "고치기" : "추가"}
          </button>
          {editing && (
            <button type="button" className="button secondary" onClick={reset} disabled={busy}>
              취소
            </button>
          )}
        </div>
        {message?.kind === "ok" && <p className="settings-saved">{message.text}</p>}
        {message?.kind === "error" && (
          <p className="error" role="alert">
            {message.text}
          </p>
        )}
      </form>
      <p className="card-note">여름·겨울 방학처럼 여러 기간을 넣을 수 있어요. 겹치는 기간은 계산할 때 하나로 합쳐요.</p>
    </Card>
  );
}
