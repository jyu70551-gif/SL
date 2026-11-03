import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

const DAYS = Array.from({ length: 31 }, (_, i) => i + 1);
// 5일장: 매달 k, k+5, k+10 … 날짜. (1·6일장, 2·7일장 … 5·10일장)
const PRESETS = [1, 2, 3, 4, 5].map((k) => ({
  label: `${k}·${k + 5}일장`,
  days: DAYS.filter((d) => d % 5 === k % 5),
}));

// "37.5000, 127.0000" 같은 글에서 위도·경도를 읽습니다. 비어 있으면 null(지움), 읽을 수 없으면 undefined.
function parseCoords(text) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const numbers = trimmed.match(/-?\d+(?:\.\d+)?/g);
  if (!numbers || numbers.length !== 2) return undefined;
  const [latitude, longitude] = numbers.map(Number);
  return { latitude, longitude };
}

const ERROR_TEXT = {
  invalid_location: "우리나라 안의 위도·경도를 입력해 주세요.",
};

// onChange(store): 불러왔을 때와 저장했을 때 현재 저장된 점포 정보를 알려 줍니다. (처음 설정 화면이 완료 단추를 열 때 씁니다)
// locationOnly: 장날 입력을 숨깁니다. (처음 설정에서는 위치만 받고, 장날은 설정 화면에서 입력)
export default function StoreCard({ onChange, locationOnly = false, title = "우리 점포" }) {
  const [store, setStore] = useState(null);
  const [city, setCity] = useState("");
  const [dong, setDong] = useState("");
  const [coords, setCoords] = useState("");
  const [marketDays, setMarketDays] = useState([]);
  const [state, setState] = useState("loading"); // loading | idle | saving | saved | failed
  const [errorText, setErrorText] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState({ status: "idle", items: [] }); // idle | loading | found | empty | no_key | failed
  const [picked, setPicked] = useState(""); // 방금 고른 주소 (저장하기 전까지만 보여 줍니다)

  useEffect(() => {
    let alive = true;
    request("/api/settings/store")
      .then((s) => {
        if (!alive) return;
        setStore(s);
        setCity(s.city);
        setDong(s.dong);
        setCoords(s.latitude == null ? "" : `${s.latitude}, ${s.longitude}`);
        setMarketDays(s.market_days);
        setState("idle");
        onChange?.(s);
      })
      .catch(() => alive && setState("failed"));
    return () => {
      alive = false;
    };
  }, []);

  function toggle(day) {
    setState("idle");
    setMarketDays((days) => (days.includes(day) ? days.filter((d) => d !== day) : [...days, day].sort((a, b) => a - b)));
  }

  async function searchAddress() {
    if (query.trim().length < 2) return;
    setSearch({ status: "loading", items: [] });
    try {
      const found = await request(`/api/settings/store/address?q=${encodeURIComponent(query.trim())}`);
      if (found.status === "no_key") setSearch({ status: "no_key", items: [] });
      else setSearch({ status: found.items.length ? "found" : "empty", items: found.items });
    } catch {
      setSearch({ status: "failed", items: [] });
    }
  }

  // 후보를 고르면 시·군·구, 동, 좌표가 채워지고 바로 저장됩니다. (고른 것이 곧 저장이라 [저장]을 따로 누를 필요가 없어요)
  function pick(item) {
    setCity(item.city);
    setDong(item.dong);
    setCoords(`${item.latitude}, ${item.longitude}`);
    setSearch({ status: "idle", items: [] });
    persist({ city: item.city, dong: item.dong, coordsText: `${item.latitude}, ${item.longitude}`, label: item.label });
  }

  function save(event) {
    event.preventDefault();
    persist();
  }

  async function persist(next = {}) {
    const parsed = parseCoords(next.coordsText ?? coords);
    if (parsed === undefined) {
      setErrorText("위도와 경도를 '37.5000, 127.0000'처럼 두 숫자로 입력해 주세요.");
      setState("failed");
      return;
    }
    setState("saving");
    try {
      const saved = await request("/api/settings/store", {
        method: "POST",
        body: { city: next.city ?? city, dong: next.dong ?? dong, market_days: marketDays, latitude: parsed?.latitude ?? null, longitude: parsed?.longitude ?? null },
      });
      setStore(saved);
      setCity(saved.city);
      setDong(saved.dong);
      setCoords(saved.latitude == null ? "" : `${saved.latitude}, ${saved.longitude}`);
      setMarketDays(saved.market_days);
      setPicked(next.label ?? "");
      setState("saved");
      // 위치가 바뀌었으니 홈의 AI 점검 요약은 옛 지역 기준입니다. 기억해 둔 것을 지우고, 홈에 가면 새로 만들게 표시합니다.
      try {
        sessionStorage.removeItem("sl.aiSummary");
        sessionStorage.setItem("sl.aiRefresh", "1");
      } catch {
        /* 저장이 막혀 있어도 화면은 정상입니다 */
      }
      onChange?.(saved);
    } catch (e) {
      setErrorText(ERROR_TEXT[e.detail?.code] ?? "저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.");
      setState("failed");
    }
  }

  const preset = PRESETS.find((p) => p.days.length === marketDays.length && p.days.every((d, i) => d === marketDays[i]));
  return (
    <Card title={title}>
      {state === "loading" && <p className="card-note">불러오는 중…</p>}
      {store && (
        <form className="settings-form" onSubmit={save}>
          {coords && (
            <p className="store-now">
              현재 점포 <strong>{[city, dong].filter(Boolean).join(" ") || "위치 등록됨"}</strong>
            </p>
          )}
          <label htmlFor="store-address">{coords ? "다른 곳으로 바꾸려면 주소 검색" : "점포 주소 검색"}</label>
          <div className="address-search">
            <input
              id="store-address"
              value={query}
              placeholder="예: 가상시 가상로 12"
              onChange={(e) => { setQuery(e.target.value); setSearch({ status: "idle", items: [] }); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); searchAddress(); } }}
            />
            <button type="button" className="button secondary" onClick={searchAddress} disabled={search.status === "loading"}>
              검색
            </button>
          </div>
          {search.status === "empty" && <p className="muted">주소를 찾지 못했어요. 도로명이나 동 이름을 바꿔서 다시 검색해 보세요.</p>}
          {search.status === "no_key" && <p className="muted">주소 검색을 쓸 수 없어요. 아래에서 위도·경도를 직접 입력해 주세요.</p>}
          {search.status === "failed" && <p className="error" role="alert">주소를 검색하지 못했어요. 잠시 뒤 다시 시도하거나 아래에서 위도·경도를 직접 입력해 주세요.</p>}
          {search.items.length > 0 && (
            <ul className="address-list">
              {search.items.map((item) => (
                <li key={`${item.label}-${item.latitude}`}>
                  <button type="button" className="text-button" onClick={() => pick(item)}>
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {state === "saved" && picked && <p className="settings-saved">저장했어요: {picked}</p>}

          <details className="address-manual" open={search.status === "no_key" || search.status === "failed"}>
            <summary>주소가 안 찾아지면 직접 입력 (시·군·구, 동, 위도·경도)</summary>
            <label htmlFor="store-city">시·군·구</label>
            <input id="store-city" value={city} maxLength={40} placeholder="예: 가상시" onChange={(e) => { setCity(e.target.value); setState("idle"); }} />
            <label htmlFor="store-dong">동</label>
            <input id="store-dong" value={dong} maxLength={40} placeholder="예: 가상동" onChange={(e) => { setDong(e.target.value); setState("idle"); }} />
            <label htmlFor="store-coords">점포 위치 (위도, 경도)</label>
            <input
              id="store-coords"
              value={coords}
              inputMode="decimal"
              placeholder="예: 37.5000, 127.0000"
              onChange={(e) => { setCoords(e.target.value); setPicked(""); setState("idle"); }}
            />
            <p className="muted">지도 앱(네이버·카카오·구글)에서 점포 위치를 길게 누르면 나오는 위도·경도를 복사해 붙여 넣으세요.</p>
            {locationOnly && (
              <button type="submit" className="button secondary" disabled={state === "saving"}>
                입력한 값 저장
              </button>
            )}
          </details>
          <p className="muted">위치는 근처 학교, 장, 날씨와 주변 상권을 찾을 때 써요.</p>

          {!locationOnly && (
          <fieldset className="settings-fieldset">
            <legend>근처 장날 (매달 이 날짜에 서요)</legend>
            <div className="day-presets">
              {PRESETS.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  className="text-button"
                  aria-pressed={preset === p}
                  onClick={() => { setMarketDays(p.days); setState("idle"); }}
                >
                  {p.label}
                </button>
              ))}
              <button type="button" className="text-button" onClick={() => { setMarketDays([]); setState("idle"); }}>
                없음
              </button>
            </div>
            <div className="day-grid">
              {DAYS.map((day) => (
                <button key={day} type="button" className="day-chip" aria-pressed={marketDays.includes(day)} onClick={() => toggle(day)}>
                  {day}
                </button>
              ))}
            </div>
            <p className="muted">
              {marketDays.length ? `매달 ${marketDays.join("·")}일` : "장날이 없으면 비워 두세요."}
            </p>
          </fieldset>
          )}

          {!locationOnly && (
            <button type="submit" className="button" disabled={state === "saving"}>
              저장
            </button>
          )}
          {state === "saving" && <p className="muted">저장하는 중…</p>}
          {state === "saved" && !picked && <p className="settings-saved">저장했어요.</p>}
          {state === "failed" && <p className="error" role="alert">{errorText || "저장하지 못했어요. 잠시 뒤 다시 시도해 주세요."}</p>}
        </form>
      )}
      {state === "failed" && !store && <p className="error" role="alert">불러오지 못했어요.</p>}
      <p className="card-note">주소 검색은 카카오 지도를 써요. 점주님이 고르거나 입력한 값만 저장하고, AI가 위치나 장날을 추측하지 않아요.</p>
    </Card>
  );
}
