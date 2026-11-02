import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

const ERROR_TEXT = {
  source_unavailable: "공식 서비스에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
};

const daysText = (days) => (days.length ? `매달 ${days.join("·")}일` : "없음");

export default function MarketCard() {
  const [data, setData] = useState(null); // null: 아직 안 찾음
  const [picked, setPicked] = useState([]);
  const [savedDays, setSavedDays] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // { kind: "ok" | "error" | "note", text }

  useEffect(() => {
    let alive = true;
    request("/api/settings/store")
      .then((s) => alive && setSavedDays(s.market_days))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  async function find() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/markets");
      setSavedDays(r.saved_days);
      if (r.status === "no_location") {
        setMessage({ kind: "note", text: "점포 위치가 아직 없어요. 처음 설정에서 주소를 먼저 등록해 주세요." });
      } else if (r.status === "no_key") {
        setMessage({ kind: "note", text: "시장 정보 인증키(MARKET_API_KEY)가 backend/.env 에 없어요." });
      } else {
        setData(r);
        // 이미 저장된 장날과 똑같은 5일장은 미리 체크해 둡니다.
        setPicked(r.items.filter((m) => m.kind === "periodic" && m.days.every((d) => r.saved_days.includes(d))).map((m) => m.market_id));
      }
    } catch (e) {
      setMessage({ kind: "error", text: ERROR_TEXT[e.detail?.code] ?? "처리하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  }

  async function save(ids) {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/markets/save", { method: "POST", body: { market_ids: ids } });
      setSavedDays(r.saved_days);
      setMessage({ kind: "ok", text: r.saved_days.length ? `장날을 ${daysText(r.saved_days)}로 저장했어요.` : "장날을 지웠어요." });
    } catch {
      setMessage({ kind: "error", text: "저장하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  }

  const toggle = (id) => setPicked((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  const items = data?.items ?? [];
  const periodic = items.filter((m) => m.kind === "periodic");
  const others = items.filter((m) => m.kind !== "periodic");

  return (
    <Card title="근처 장날 가져오기">
      <p className="card-note">
        점포 근처 {data?.radius_m ?? 500}m 안의 전통시장을 공식 자료에서 찾아 장이 서는 날을 알려 드려요. 확인하신 것만 저장돼요.
      </p>
      <p className="card-note">
        현재 저장된 장날: <strong>{savedDays.length ? daysText(savedDays) : "없음"}</strong>
      </p>
      <button type="button" className="button" onClick={find} disabled={busy}>
        {busy && !data ? "찾는 중…" : "근처 장 찾기"}
      </button>

      {data && items.length === 0 && <p className="card-note">점포에서 {data.radius_m}m 안에 전통시장이 없어요.</p>}

      {periodic.length > 0 && (
        <>
          <p className="card-note">장날로 반영할 시장을 골라 주세요. (점포에서 가까운 순서)</p>
          <ul className="school-list">
            {periodic.map((m) => (
              <li key={m.market_id}>
                <label className="check-row">
                  <input type="checkbox" checked={picked.includes(m.market_id)} onChange={() => toggle(m.market_id)} />
                  <span>
                    <strong>{m.name}</strong>
                    <span className="muted"> · {m.distance_m}m · {daysText(m.days)}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="button-row">
            <button type="button" className="button" onClick={() => save(picked)} disabled={busy}>
              {picked.length ? "선택한 장날 저장" : "장날 없음으로 저장"}
            </button>
          </div>
        </>
      )}

      {others.length > 0 && (
        <ul className="school-list">
          {others.map((m) => (
            <li key={m.market_id}>
              <strong>{m.name}</strong>
              <span className="muted">
                {" "}· {m.distance_m}m ·{" "}
                {m.kind === "permanent" ? "상설시장이라 매일 열려서 장날로 넣지 않아요" : `장이 서는 날을 읽을 수 없어요 (${m.cycle})`}
              </span>
            </li>
          ))}
        </ul>
      )}

      {data && periodic.length === 0 && items.length > 0 && savedDays.length > 0 && (
        <div className="button-row">
          <button type="button" className="button secondary" onClick={() => save([])} disabled={busy}>
            저장된 장날 지우기
          </button>
        </div>
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
