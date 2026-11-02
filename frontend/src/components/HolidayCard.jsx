import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

function dayText(iso) {
  const [, m, d] = iso.split("-").map(Number);
  return `${m}월 ${d}일`;
}

export default function HolidayCard() {
  const [counts, setCounts] = useState(null);
  const [preview, setPreview] = useState(null); // null: 아직 안 읽음
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // { kind: "ok" | "error" | "note", text }

  useEffect(() => {
    let alive = true;
    request("/api/settings/holidays")
      .then((c) => alive && setCounts(c))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  async function load() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/holidays/preview", { method: "POST" });
      if (r.status === "no_key") setMessage({ kind: "note", text: "공휴일 인증키(HOLIDAY_API_KEY)가 backend/.env 에 없어요." });
      else setPreview(r.items);
    } catch {
      setMessage({ kind: "error", text: "공식 서비스에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/holidays/save", { method: "POST" });
      setCounts(r);
      setPreview(null);
      setMessage({ kind: "ok", text: r.saved ? `공휴일 ${r.saved}일을 저장했어요.` : "이미 모두 저장돼 있어요." });
    } catch {
      setMessage({ kind: "error", text: "저장하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  }

  const fresh = preview ? preview.filter((h) => !h.already_saved).length : 0;
  return (
    <Card title="공휴일 가져오기">
      <p className="card-note">공식 특일 정보(한국천문연구원)에서 올해와 내년 공휴일을 가져와요. 대체공휴일도 함께 들어와요.</p>
      {counts && (
        <p className="card-note">
          저장된 공휴일: 올해 <strong>{counts.this_year_count}일</strong> · 내년 <strong>{counts.next_year_count}일</strong>
        </p>
      )}
      {!preview && (
        <button type="button" className="button" onClick={load} disabled={busy}>
          {busy ? "가져오는 중…" : "공휴일 가져오기"}
        </button>
      )}
      {preview && (
        <>
          <ul className="school-list">
            {preview.map((h) => (
              <li key={`${h.date}-${h.name}`}>
                <strong>{dayText(h.date)}</strong> {h.name}
                {h.already_saved && <span className="muted"> · 이미 저장됨</span>}
              </li>
            ))}
          </ul>
          <div className="button-row">
            <button type="button" className="button" onClick={save} disabled={busy || fresh === 0}>
              {fresh ? `공휴일 ${fresh}일 저장` : "모두 저장돼 있어요"}
            </button>
            <button type="button" className="button secondary" onClick={() => setPreview(null)} disabled={busy}>
              닫기
            </button>
          </div>
        </>
      )}
      {message?.kind === "ok" && <p className="settings-saved">{message.text}</p>}
      {message?.kind === "note" && <p className="card-note">{message.text}</p>}
      {message?.kind === "error" && (
        <p className="error" role="alert">
          {message.text}
        </p>
      )}
    </Card>
  );
}
