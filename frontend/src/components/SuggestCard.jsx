import { useEffect, useRef, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";
import { Mascot } from "./StoreScene.jsx";

const UNAVAILABLE = {
  off: "AI 기능이 꺼져 있어요.",
  no_key: "AI 연결 키가 아직 없어요.",
  limit: "이번 달 AI 사용 한도에 도달했어요.",
  degraded: "AI 연결이 불안정해서 잠시 쉬고 있어요.",
  key_invalid: "AI 연결 키가 올바르지 않아요.",
};

// 오늘 만든 결과는 이 브라우저 탭에 잠깐 기억해 두었다가 홈에 다시 오면 바로 보여 줍니다. (AI를 다시 부르지 않습니다)
const STORE_KEY = "sl.aiSummary";

function dayKey() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function remembered() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
    return saved && saved.day === dayKey() && saved.data?.status === "ok" ? saved.data : null;
  } catch {
    return null;
  }
}

// 점포 위치를 바꾸면 StoreCard가 이 표시를 남깁니다. 홈에 오면 한 번 자동으로 새로 만듭니다.
const REFRESH_KEY = "sl.aiRefresh";

function takeRefreshFlag() {
  try {
    const on = sessionStorage.getItem(REFRESH_KEY) === "1";
    if (on) sessionStorage.removeItem(REFRESH_KEY);
    return on;
  } catch {
    return false;
  }
}

function remember(data) {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify({ day: dayKey(), data }));
  } catch {
    /* 저장이 막혀 있어도 화면은 정상입니다 */
  }
}

function FactList({ facts }) {
  const groups = [...new Set(facts.map((f) => f.group))];
  return (
    <div className="suggest-facts">
      {groups.map((group) => (
        <div key={group}>
          <h3 className="group-title">{group}</h3>
          <ul className="basis-list">
            {facts.filter((f) => f.group === group).map((f) => (
              <li key={f.id}>{f.text}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

// 눌렀을 때만 AI 점검 요약을 만듭니다. 근거가 된 사실은 코드가 모은 것이고, 요약 문장만 AI가 씁니다.
// 결과가 있으면 가장 중요한 한 가지를 바로 보여 주고, 나머지와 근거는 펼쳐서 봅니다.
export default function SuggestCard() {
  const [data, setData] = useState(remembered);
  const [state, setState] = useState(() => (remembered() ? "done" : "idle")); // idle | loading | done | error
  const [open, setOpen] = useState(false);
  const autoRef = useRef(false);

  useEffect(() => {
    if (autoRef.current) return;
    autoRef.current = true;
    if (takeRefreshFlag()) make(true);
  }, []);

  async function make(refresh = false) {
    setState("loading");
    try {
      const result = await request("/api/suggestions", { method: "POST", body: { refresh } });
      setData(result);
      setOpen(false);
      setState("done");
      if (result.status === "ok") remember(result);
    } catch {
      setState("error");
    }
  }

  const ok = state === "done" && data?.status === "ok";
  const cards = ok ? data.cards.slice(0, 3) : [];
  const used = ok ? data.cards.flatMap((c) => c.facts) : [];
  const usedFacts = [...new Map(used.map((f) => [f.id, f])).values()];

  return (
    <Card title="AI 점검 요약">
      <Mascot />
      {state === "idle" && (
        <>
          <p className="card-note">날짜, 근처 학교 방학, 주변 상권, 날씨를 보고 오늘 해 볼 만한 일을 정리해 드려요. 누를 때만 만들어요.</p>
          <button type="button" className="button" onClick={() => make(false)}>
            오늘 점검 요약 만들기
          </button>
        </>
      )}
      {state === "loading" && <p className="card-note" role="status">살펴보고 있어요…</p>}
      {state === "error" && (
        <>
          <p className="card-note">요약을 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.</p>
          <button type="button" className="button secondary" onClick={() => make(false)}>
            다시 시도
          </button>
        </>
      )}

      {state === "done" && data?.status === "unavailable" && (
        <>
          <p className="card-note">{UNAVAILABLE[data.state] ?? "AI를 쓸 수 없어요."} 대신 오늘 알아 둘 점을 보여 드려요.</p>
          <FactList facts={data.facts} />
        </>
      )}
      {state === "done" && data?.status === "failed" && (
        <>
          <p className="card-note">요약을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요. 대신 오늘 알아 둘 점을 보여 드려요.</p>
          <FactList facts={data.facts} />
          <button type="button" className="button secondary" onClick={() => make(true)}>
            다시 만들기
          </button>
        </>
      )}

      {ok && (
        <>
          <ol className="suggest-list">
            {cards.map((card) => (
              <li key={card.title} className="suggest-item">
                <strong className="suggest-title">{card.title}</strong>
                <p className="suggest-body">{card.body}</p>
              </li>
            ))}
          </ol>
          <p className="card-note">외부 정보로 짐작한 아이디어예요. 판매 자료로 확인한 내용은 아니에요.</p>
          <div className="basis-row">
            <button type="button" className="text-button" aria-expanded={open} onClick={() => setOpen(!open)}>
              근거 보기 {open ? "▴" : "▾"}
            </button>
          </div>
          {open && (
            <div className="ai-more">
              <FactList facts={usedFacts} />
              <button type="button" className="button secondary" onClick={() => make(true)}>
                다시 만들기
              </button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
