import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

const NOTE = {
  no_location: "점포 위치가 아직 없어요. 처음 설정에서 주소를 먼저 등록해 주세요.",
  no_key: "과거 날씨 인증키(WEATHER_PAST_API_KEY)가 backend/.env 에 없어요.",
};

// 가장 가까운 관측소가 너무 멀면 날씨를 쓰지 않아요. (모형은 날씨 없이 예상합니다)
const farText = (info) =>
  `가장 가까운 관측소(${info.station.name})가 약 ${info.station.distance_km}km 떨어져 있어서(기준 ${info.max_km}km) 날씨를 가져오지 않아요. 내일 예상 매출은 날씨 없이 계산해요.`;

// 내일 예상 매출 모형이 배우는 과거 날씨(기상청 관측)를 받아 저장합니다. 점포에서 가장 가까운 관측소 값입니다.
export default function WeatherCard() {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null); // { kind: "ok" | "note" | "error", text }

  useEffect(() => {
    let alive = true;
    request("/api/settings/weather")
      .then((r) => alive && setInfo(r))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  async function sync() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await request("/api/settings/weather/sync", { method: "POST" });
      if (r.status === "too_far") {
        setInfo({ ...info, ...r });
        setMessage({ kind: "note", text: farText(r) });
      } else if (NOTE[r.status]) {
        setMessage({ kind: "note", text: NOTE[r.status] });
      } else {
        setInfo({ ...info, ...r });
        setMessage({ kind: "ok", text: r.asked === 0 ? "빠진 날이 없어요." : `${r.added}일의 날씨를 저장했어요.` });
      }
    } catch {
      setMessage({ kind: "error", text: "기상청에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="과거 날씨 가져오기">
      <p className="card-note">
        내일 예상 매출은 과거 날씨(평균 기온, 비 온 날)와 매출의 관계를 배워서 계산해요. 매출이 있는 날의 날씨를 기상청에서 가져와요.
      </p>
      {info?.station && info.status !== "too_far" && (
        <p className="card-note">
          가장 가까운 관측소: <strong>{info.station.name}</strong> (약 {info.station.distance_km}km). 점포와 떨어져 있어서 비가 온 날이 다를 수 있어요.
        </p>
      )}
      {info?.status === "too_far" && <p className="card-note">{farText(info)}</p>}
      {info?.station && info.stations?.some((name) => name !== info.station.name) && info.status !== "too_far" && (
        <p className="card-note">
          저장된 날씨 중에 <strong>다른 관측소({info.stations.filter((name) => name !== info.station.name).join(", ")})</strong> 것이 섞여 있어요. 점포 위치를 바꿨다면 지금 점포의 날씨와 다를 수 있어요.
        </p>
      )}
      {info && (
        <p className="card-note">
          저장된 날씨: <strong>{info.days}일</strong>
          {info.missing > 0 && <> · 빠진 날 {info.missing}일</>}
        </p>
      )}
      {info && info.missing === 0 && info.status !== "too_far" ? (
        <p className="done-line">✓ 모든 날의 날씨가 저장돼 있어요.</p>
      ) : (
        <button type="button" className="button" onClick={sync} disabled={busy || info?.status === "too_far"}>
          {busy ? "가져오는 중…" : "빠진 날 날씨 가져오기"}
        </button>
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
