import { useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";

const UNAVAILABLE = {
  off: "AI 기능이 꺼져 있어요.",
  no_key: "AI 연결 키가 아직 없어요.",
  limit: "이번 달 AI 사용 한도에 도달했어요.",
  degraded: "AI 연결이 불안정해서 잠시 쉬고 있어요.",
  key_invalid: "AI 연결 키가 올바르지 않아요.",
};

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

// 눌렀을 때만 AI 제안을 만듭니다. 근거가 된 사실은 코드가 모은 것이고, 제안 문장만 AI가 씁니다.
export default function SuggestCard() {
  const [state, setState] = useState("idle"); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [showFacts, setShowFacts] = useState(false);

  async function listen(refresh = false) {
    setState("loading");
    try {
      setData(await request("/api/suggestions", { method: "POST", body: { refresh } }));
      setState("done");
    } catch {
      setState("error");
    }
  }

  const ok = state === "done" && data?.status === "ok";
  const used = ok ? data.cards.flatMap((c) => c.facts) : [];
  const usedFacts = [...new Map(used.map((f) => [f.id, f])).values()];

  return (
    <Card title="AI 제안">
      {state === "idle" && (
        <>
          <p className="card-note">오늘 날짜, 근처 학교 방학, 주변 시설, 날씨를 보고 오늘 해 볼 만한 걸 알려 드려요.</p>
          <button type="button" className="button" onClick={() => listen(false)}>
            AI 제안 듣기
          </button>
        </>
      )}
      {state === "loading" && <p className="card-note">살펴보고 있어요…</p>}
      {state === "error" && (
        <>
          <p className="card-note">제안을 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.</p>
          <button type="button" className="button secondary" onClick={() => listen(false)}>
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
          <p className="card-note">제안을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요. 대신 오늘 알아 둘 점을 보여 드려요.</p>
          <FactList facts={data.facts} />
          <button type="button" className="button secondary" onClick={() => listen(true)}>
            다시 듣기
          </button>
        </>
      )}

      {ok && (
        <>
          <ul className="suggest-list">
            {data.cards.map((card) => (
              <li key={card.title} className="suggest-item">
                <strong className="suggest-title">{card.title}</strong>
                <p className="suggest-body">{card.body}</p>
                <p className="muted">근거: {[...new Set(card.facts.map((f) => f.group))].join(" · ")}</p>
              </li>
            ))}
          </ul>
          <div className="basis-row">
            <button type="button" className="text-button" aria-expanded={showFacts} onClick={() => setShowFacts(!showFacts)}>
              근거로 쓴 사실 {showFacts ? "▴" : "▾"}
            </button>
            <button type="button" className="text-button" onClick={() => listen(true)}>
              다시 듣기
            </button>
          </div>
          {showFacts && <FactList facts={usedFacts} />}
          <p className="card-note">AI가 낸 아이디어예요. 실제 판매 자료가 아니라 날짜·시설·날씨를 보고 짐작한 거라서 참고만 해 주세요.</p>
        </>
      )}
    </Card>
  );
}
