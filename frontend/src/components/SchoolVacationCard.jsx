import { useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

const ERROR_TEXT = {
  source_unavailable: "공식 서비스에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.",
  invalid_schools: "학교를 1곳 이상, 10곳 이하로 골라 주세요.",
};

const STATUS_TEXT = {
  no_code: "공식 학사일정에서 이 학교를 찾지 못했어요. 이 학교의 방학은 가져올 수 없어요.",
  none_found: "방학으로 볼 수 있는 일정이 아직 없어요. ",
  unavailable: "이 학교의 일정을 가져오지 못했어요. 잠시 뒤 다시 시도해 주세요.",
};

function dateText(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

export default function SchoolVacationCard({ onSaved }) {
  const [step, setStep] = useState("start"); // start | schools | preview
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // { kind: "ok" | "error" | "note", text }
  const [schools, setSchools] = useState([]);
  const [picked, setPicked] = useState([]); // 고른 학교 id
  const [preview, setPreview] = useState([]);
  const [chosen, setChosen] = useState({}); // "학교id|시작|끝" -> true

  function fail(error) {
    setMessage({ kind: "error", text: ERROR_TEXT[error.detail?.code] ?? "처리하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
  }

  async function findSchools() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/schools");
      if (r.status === "no_location") {
        setMessage({ kind: "note", text: "점포 위치가 아직 없어요. 처음 설정에서 주소를 먼저 등록해 주세요." });
      } else if (r.status === "no_key") {
        setMessage({ kind: "note", text: "공공데이터포털 인증키(DATA_GO_KR_API_KEY)가 backend/.env 에 없어요." });
      } else if (r.items.length === 0) {
        setMessage({ kind: "note", text: `점포에서 ${r.radius_m}m 안에 학교가 없어요.` });
      } else {
        setSchools(r.items);
        setPicked(r.items.map((s) => s.school_id));
        setStep("schools");
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function showPreview() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/schools/vacations", { method: "POST", body: { school_ids: picked } });
      if (r.status === "no_key") {
        setMessage({ kind: "note", text: "NEIS 인증키(NEIS_API_KEY)가 backend/.env 에 없어요." });
        return;
      }
      setPreview(r.schools);
      const next = {};
      for (const school of r.schools) {
        for (const p of school.periods) {
          if (!p.already_saved) next[`${school.school_id}|${p.start_date}|${p.end_date}`] = true;
        }
      }
      setChosen(next);
      setStep("preview");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    const items = [];
    for (const school of preview) {
      for (const p of school.periods) {
        if (chosen[`${school.school_id}|${p.start_date}|${p.end_date}`]) {
          items.push({ school_id: school.school_id, label: p.label, start_date: p.start_date, end_date: p.end_date });
        }
      }
    }
    if (items.length === 0) return;
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/schools/vacations/save", { method: "POST", body: { items } });
      setMessage({ kind: "ok", text: `${r.saved}건을 방학 기간에 저장했어요.` });
      setStep("start");
      onSaved?.();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  const toggleSchool = (id) => setPicked((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]));
  const togglePeriod = (key) => setChosen((c) => ({ ...c, [key]: !c[key] }));
  const chosenCount = Object.values(chosen).filter(Boolean).length;
  const periods = preview.flatMap((school) => school.periods);
  const allSaved = periods.length > 0 && periods.every((p) => p.already_saved);

  return (
    <Card title="근처 학교 방학 가져오기">
      {step === "start" && (
        <>
          <p className="card-note">점포 근처 500m 안 학교의 공식 학사일정에서 방학 기간을 찾아 드려요. 확인하신 것만 저장돼요.</p>
          <button type="button" className="button" onClick={findSchools} disabled={busy}>
            {busy ? "찾는 중…" : "근처 학교 찾기"}
          </button>
        </>
      )}

      {step === "schools" && (
        <>
          <p className="card-note">방학을 반영할 학교를 골라 주세요. (점포에서 가까운 순서)</p>
          <ul className="school-list">
            {schools.map((s) => (
              <li key={s.school_id}>
                <label className="check-row">
                  <input type="checkbox" checked={picked.includes(s.school_id)} onChange={() => toggleSchool(s.school_id)} />
                  <span>
                    <strong>{s.name}</strong>
                    <span className="muted"> · {s.kind} · {s.distance_m}m</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="button-row">
            <button type="button" className="button" onClick={showPreview} disabled={busy || picked.length === 0}>
              {busy ? "가져오는 중…" : "방학 일정 보기"}
            </button>
            <button type="button" className="button secondary" onClick={() => setStep("start")} disabled={busy}>
              취소
            </button>
          </div>
        </>
      )}

      {step === "preview" && (
        <>
          <p className="card-note">학교가 공식 학사일정에 적은 방학이에요. 맞는 것만 체크해서 저장해 주세요.</p>
          {allSaved && <p className="settings-saved">이 학교들의 방학은 이미 모두 저장돼 있어요. (체크가 잠겨 있는 건 저장됐다는 뜻이에요)</p>}
          {preview.map((school) => (
            <div key={school.school_id} className="school-block">
              <h3 className="group-title">{school.name}</h3>
              {school.periods.length === 0 && <p className="card-note">{STATUS_TEXT[school.status] ?? ""}</p>}
              <ul className="school-list">
                {school.periods.map((p) => {
                  const key = `${school.school_id}|${p.start_date}|${p.end_date}`;
                  return (
                    <li key={key}>
                      <label className="check-row">
                        <input type="checkbox" checked={p.already_saved || Boolean(chosen[key])} disabled={p.already_saved} onChange={() => togglePeriod(key)} />
                        <span>
                          {p.label} · {dateText(p.start_date)} ~ {dateText(p.end_date)} ({p.days}일)
                          {p.already_saved && <span className="muted"> · 이미 저장됨</span>}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          <div className="button-row">
            <button type="button" className="button" onClick={save} disabled={busy || chosenCount === 0}>
              {busy ? "저장 중…" : allSaved ? "모두 저장돼 있어요" : `선택한 방학 저장 (${chosenCount}건)`}
            </button>
            <button type="button" className="button secondary" onClick={() => setStep("schools")} disabled={busy}>
              이전
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
      <p className="card-note">공식 학사일정이 아직 올라오지 않았거나 학교가 달리 적은 경우에는 찾지 못할 수 있어요.</p>
    </Card>
  );
}
