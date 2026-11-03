import { useEffect, useRef, useState } from "react";
import { request } from "../api.js";
import HolidayCard from "../components/HolidayCard.jsx";
import MarketCard from "../components/MarketCard.jsx";
import WeatherCard from "../components/WeatherCard.jsx";
import PasswordCard from "../components/PasswordCard.jsx";
import SchoolVacationCard from "../components/SchoolVacationCard.jsx";
import StoreCard from "../components/StoreCard.jsx";

// 설정은 '처음 한 번 정하는 것'과 '가끔 관리하는 것'을 네 묶음으로 나눠, 한 번에 한 묶음만 보여 줍니다.
const GROUPS = [
  { id: "store", label: "점포 정보", note: "점포 주소와 현재 위치" },
  { id: "data", label: "분석 데이터", note: "매출을 비교할 때 참고하는 자료" },
  { id: "alert", label: "알림 설정", note: "확인할 사항을 얼마나 자주 올릴지" },
  { id: "account", label: "계정·보안", note: "비밀번호" },
];

// 알림 민감도는 서버가 주는 낮음·보통·높음 대신, 점주에게 와닿는 말로 보여 줍니다. (저장되는 값은 그대로 low·normal·high)
const SENSITIVITY_TEXT = {
  low: { label: "큰 변화 위주", text: "눈에 띄게 달라진 것만 올려요. 알림이 적어요." },
  normal: { label: "균형 있게", text: "보통 수준의 변화부터 올려요." },
  high: { label: "작은 변화까지", text: "작은 변화도 일찍 알려요. 알림이 늘어나요." },
};

function Sensitivity() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    request("/api/settings/sensitivity")
      .then((d) => alive && setData(d))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  async function choose(level) {
    if (saving || data?.level === level) return;
    setSaving(true);
    setFailed(false);
    setSaved(false);
    try {
      setData(await request("/api/settings/sensitivity", { method: "POST", body: { level } }));
      setSaved(true);
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      {!data && !failed && <p className="card-note">불러오는 중…</p>}
      {data && (
        <div className="sensitivity" role="radiogroup" aria-label="알림 민감도">
          {data.options.map((option) => {
            const words = SENSITIVITY_TEXT[option.level] ?? { label: option.label, text: option.text };
            return (
              <label key={option.level} className={`sensitivity-option${data.level === option.level ? " selected" : ""}`}>
                <input
                  type="radio"
                  name="sensitivity"
                  value={option.level}
                  checked={data.level === option.level}
                  disabled={saving}
                  onChange={() => choose(option.level)}
                />
                <span>
                  <strong>{words.label}</strong>
                  <span className="sensitivity-text">{words.text}</span>
                </span>
              </label>
            );
          })}
        </div>
      )}
      {saved && <p className="settings-saved">바꿨어요.</p>}
      {failed && (
        <p className="error" role="alert">
          설정을 불러오거나 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.
        </p>
      )}
      <p className="muted">고르는 즉시 반영돼요. 알림이 너무 많으면 &lsquo;큰 변화 위주&rsquo;로, 놓치는 게 걱정되면 &lsquo;작은 변화까지&rsquo;로 바꿔 보세요.</p>
    </div>
  );
}

// 분석 데이터 한 줄: 이름, 실제 상태, 상태 배지, 관리 버튼. 누르면 아래로 기존 가져오기·관리 화면이 펼쳐집니다.
function DataRow({ id, name, line, state, action, open, onToggle, children }) {
  return (
    <li className={`data-row ${state.tone}`} id={id}>
      <div className="data-row-main">
        <div className="data-row-text">
          <strong>{name}</strong>
          <span className="data-row-line">{line}</span>
        </div>
        <span className={`status-badge ${state.tone}`}>{state.text}</span>
        {action && (
          <button type="button" className="button secondary" aria-expanded={open} onClick={onToggle}>
            {open ? "닫기" : action}
          </button>
        )}
      </div>
      {open && <div className="data-row-detail embedded">{children}</div>}
    </li>
  );
}

function rowsFrom(info) {
  const { store, vacations, holidays, weather } = info;
  const vacationCount = vacations?.items?.length ?? 0;
  const holidayCount = holidays?.this_year_count ?? 0;
  const marketDays = store?.market_days ?? [];
  const weatherNone = !weather?.days;
  const weatherTooFar = weather?.status === "too_far";
  const weatherMissing = (weather?.missing ?? 0) > 0;
  let weatherState = { tone: "ok", text: "자동" };
  if (weatherTooFar || weatherMissing) weatherState = { tone: "warn", text: "확인 필요" };
  if (weatherNone && !weatherTooFar) weatherState = { tone: "warn", text: "확인 필요" };
  let weatherLine = `저장된 날씨 ${weather?.days}일${weatherMissing ? ` · 빠진 날 ${weather?.missing}일` : ""}${weather?.last_day ? ` · ${weather.last_day}까지` : ""}`;
  if (weatherTooFar) weatherLine = "가까운 기상 관측소가 멀어서 가져올 수 없어요.";
  else if (weatherNone) weatherLine = "날씨를 자동으로 가져오지 못했어요. 직접 가져올 수 있어요.";
  return [
    {
      id: "school",
      name: "학교 방학",
      // 점포 위치를 저장하면 근처 학교의 방학을 서버가 알아서 가져옵니다. 못 가져왔을 때만 직접 가져오게 합니다.
      line: vacationCount ? `방학 일정 ${vacationCount}건 · 위치를 바꾸면 자동으로 다시 가져와요` : "근처 학교의 방학을 자동으로 가져오지 못했어요. 직접 가져올 수 있어요.",
      state: vacationCount ? { tone: "ok", text: "자동" } : { tone: "warn", text: "확인 필요" },
      action: vacationCount ? "관리" : "직접 가져오기",
      detail: <SchoolVacationCard />,
    },
    {
      id: "holiday",
      name: "공휴일",
      // 공휴일은 홈을 열 때 서버가 알아서 가져옵니다. 자동으로 안 됐을 때만 직접 가져오는 버튼을 보여 줍니다.
      line: holidayCount ? `올해 ${holidayCount}일 · 자동으로 반영돼요` : "아직 자동으로 가져오지 못했어요. 홈을 열 때 다시 시도해요.",
      state: holidayCount ? { tone: "ok", text: "자동" } : { tone: "warn", text: "확인 필요" },
      action: holidayCount ? null : "지금 가져오기",
      detail: <HolidayCard />,
    },
    {
      id: "market",
      name: "장날",
      line: marketDays.length ? `매달 ${marketDays.join("·")}일` : "근처에 5일장이 하나뿐이면 자동으로 정해요. 여러 곳이거나 없으면 직접 골라 주세요. 없어도 돼요.",
      state: marketDays.length ? { tone: "ok", text: "저장됨" } : { tone: "optional", text: "선택" },
      action: marketDays.length ? "관리" : "입력하기",
      detail: <MarketCard />,
    },
    {
      id: "weather",
      name: "날씨",
      line: weatherLine,
      state: weatherState,
      action: weatherNone || weatherMissing ? "직접 가져오기" : "관리",
      detail: <WeatherCard />,
    },
  ];
}

export default function Settings() {
  const [group, setGroup] = useState(() => {
    const id = window.location.hash.replace("#", "");
    return GROUPS.some((g) => g.id === id) ? id : "store";
  });
  const [info, setInfo] = useState(null);
  const [openRow, setOpenRow] = useState(null);
  const [changing, setChanging] = useState(false);
  const [tick, setTick] = useState(0);
  const timer = useRef(null);

  // 어느 칸에서든 저장하면 요약이 곧 새로 고쳐지도록, 누르거나 바꾼 뒤 잠깐 있다가 다시 읽습니다.
  const refresh = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setTick((t) => t + 1), 1500);
  };
  useEffect(() => () => clearTimeout(timer.current), []);

  // 뒤로 가기나 주소 끝(#data 등)이 바뀌어도 그 묶음을 보여 줍니다.
  useEffect(() => {
    const onHash = () => {
      const id = window.location.hash.replace("#", "");
      if (GROUPS.some((g) => g.id === id)) setGroup(id);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([
      request("/api/settings/store"),
      request("/api/settings/vacations"),
      request("/api/settings/holidays"),
      request("/api/settings/weather"),
    ]).then(([store, vacations, holidays, weather]) => {
      if (alive) setInfo({ store: store.value, vacations: vacations.value, holidays: holidays.value, weather: weather.value });
    });
    return () => {
      alive = false;
    };
  }, [tick]);

  function go(id, row = null) {
    setGroup(id);
    setOpenRow(row);
    window.history.replaceState(null, "", `#${id}`);
  }

  const store = info?.store;
  const hasLocation = store?.latitude != null;
  const rows = info ? rowsFrom(info) : [];
  const todo = [
    ...(info && !hasLocation ? [{ group: "store", row: null }] : []),
    ...rows.filter((r) => r.state.tone === "todo" || r.state.tone === "warn").map((r) => ({ group: "data", row: r.id })),
  ];
  const place = store && [store.city, store.dong].filter(Boolean).join(" ");
  const current = GROUPS.find((g) => g.id === group);

  return (
    <section className="settings-page" onClickCapture={refresh} onChangeCapture={refresh}>
      <header className="settings-head">
        <div>
          <h1 className="page-title">설정</h1>
          <p className="page-meta">매장과 분석에 필요한 정보를 관리해요.</p>
        </div>
        {info &&
          (todo.length > 0 ? (
            <button type="button" className="todo-summary" onClick={() => go(todo[0].group, todo[0].row)}>
              설정이 필요한 항목 <strong>{todo.length}개</strong> <span aria-hidden="true">›</span>
            </button>
          ) : (
            <span className="todo-summary done">✓ 필요한 설정이 모두 끝났어요</span>
          ))}
      </header>

      <div className="settings-layout">
        <nav className="settings-menu" aria-label="설정 메뉴">
          {GROUPS.map((g) => (
            <button
              key={g.id}
              type="button"
              className={`settings-tab${group === g.id ? " on" : ""}`}
              aria-current={group === g.id ? "page" : undefined}
              onClick={() => go(g.id)}
            >
              {g.label}
            </button>
          ))}
        </nav>

        <div className="settings-body">
          <h2 className="settings-title">{current.label}</h2>
          <p className="settings-sub">{current.note}</p>

          {group === "store" && (
            <div className="settings-panel">
              <p className="settings-label">현재 저장된 주소</p>
              {hasLocation ? (
                <p className="address-now">{place || "위치가 등록돼 있어요"}</p>
              ) : (
                <p className="address-now none">아직 등록하지 않았어요</p>
              )}
              {hasLocation && <p className="muted">근처 학교, 날씨, 주변 상권을 찾을 때 이 위치를 써요.</p>}
              {hasLocation && !changing && (
                <button type="button" className="button secondary" onClick={() => setChanging(true)}>
                  주소 변경
                </button>
              )}
              {(!hasLocation || changing) && (
                <div className="embedded">
                  <p className="muted save-how">검색한 주소를 고르면 바로 저장돼요. 직접 입력한 값은 &lsquo;입력한 값 저장&rsquo;을 눌러야 저장돼요.</p>
                  <StoreCard locationOnly title="주소 변경" />
                  {hasLocation && (
                    <button type="button" className="text-button" onClick={() => setChanging(false)}>
                      닫기
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {group === "data" && (
            <div className="settings-panel">
              {!info && <p className="card-note">불러오는 중…</p>}
              <ul className="data-list">
                {rows.map((r) => (
                  <DataRow
                    key={r.id}
                    id={`set-${r.id}`}
                    name={r.name}
                    line={r.line}
                    state={r.state}
                    action={r.action}
                    open={openRow === r.id}
                    onToggle={() => setOpenRow(openRow === r.id ? null : r.id)}
                  >
                    {r.detail}
                  </DataRow>
                ))}
              </ul>
              <p className="muted">가져오기는 미리 보고 저장하는 것과 바로 저장되는 것이 있어요. 각 칸의 안내를 따라 주세요.</p>
            </div>
          )}

          {group === "alert" && (
            <div className="settings-panel">
              <Sensitivity />
            </div>
          )}

          {group === "account" && (
            <div className="settings-panel embedded">
              <PasswordCard />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
