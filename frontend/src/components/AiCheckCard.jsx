import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "../api.js";
import { STORE } from "../reasons.js";
import { Card } from "./Card.jsx";
import FeedbackButtons from "./FeedbackButtons.jsx";
import { AlertTriangle } from "./Icons.jsx";
import NoteBox from "./NoteBox.jsx";

const POLL_MS = 3000;
const POLL_MAX = 10; // 준비 중이면 3초 간격으로 최대 30초까지 다시 조회
const UNDO_MS = 8000;

// AI를 쓰지 못할 때 왜 고정 문구인지 한 줄로 알려줍니다. (꺼짐·키 없음은 조용히 넘어갑니다)
const FIXED_NOTE = {
  limit: "이번 달 AI 사용 한도에 도달해서 계산 결과로 보여드려요.",
  degraded: "AI 연결이 불안정해서 계산 결과로 보여드려요.",
  key_invalid: "AI 연결 키가 올바르지 않아 계산 결과로 보여드려요.",
};

export default function AiCheckCard({ onChanged }) {
  const [view, setView] = useState(null);
  const [failed, setFailed] = useState(false);
  const [error, setError] = useState(false);
  const [undo, setUndo] = useState(null);
  const [openNote, setOpenNote] = useState(null); // 한마디 입력을 열어 둔 항목 id 또는 "free"
  const polls = useRef(0);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setView(await request("/api/ai/briefing"));
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // 점검이 만들어지는 중이면 잠시 뒤 다시 확인합니다.
  useEffect(() => {
    if (view?.status !== "pending") {
      polls.current = 0;
      return undefined;
    }
    if (polls.current >= POLL_MAX) return undefined;
    const timer = setTimeout(() => {
      polls.current += 1;
      load();
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [view, load]);

  useEffect(() => {
    if (!undo) return undefined;
    const timer = setTimeout(() => setUndo(null), UNDO_MS);
    return () => clearTimeout(timer);
  }, [undo]);

  async function quick(item, reason) {
    const category = item.kind === "category" ? item.category : STORE;
    setError(false);
    try {
      await request("/api/anomalies/review", { method: "POST", body: { category, dates: [item.date], reasons: [reason] } });
      setUndo({ category, date: item.date });
      await load();
      onChanged?.();
    } catch {
      setError(true); // 저장되지 않았으면 항목은 그대로 둡니다
    }
  }

  async function undoRecord() {
    try {
      await request("/api/anomalies/unreview", { method: "POST", body: { category: undo.category, date: undo.date } });
      setUndo(null);
      await load();
      onChanged?.();
    } catch {
      setError(true);
    }
  }

  const title = "오늘의 점검";
  if (!view && !failed) {
    return (
      <Card title={title}>
        <p className="card-note">점검을 불러오는 중…</p>
      </Card>
    );
  }
  if (failed) {
    return (
      <Card title={title}>
        <p className="card-note">점검을 불러오지 못했어요.</p>
        <button type="button" className="text-button" onClick={load}>
          다시 시도
        </button>
      </Card>
    );
  }
  if (view.status === "none") return null;

  const isAi = view.mode === "ai";
  const aiState = view.ai?.state;

  if (view.status === "pending") {
    const gaveUp = polls.current >= POLL_MAX;
    return (
      <Card title={title}>
        <p className="card-note" aria-live="polite">
          {gaveUp ? "점검이 아직 준비되지 않았어요. 잠시 후 다시 열어 주세요." : "점검을 준비하고 있어요…"}
        </p>
        {gaveUp && (
          <button type="button" className="text-button" onClick={load}>
            다시 확인
          </button>
        )}
      </Card>
    );
  }

  return (
    <Card title={title} aside={isAi ? <span className="ai-badge">AI가 정리</span> : null}>
      <p className="ai-headline">{view.headline}</p>

      <ul className="ai-items">
        {view.items.map((item, index) => (
          <li key={item.id} className="ai-item">
            <div className="ai-item-title">
              <AlertTriangle className="note-icon" size={18} />
              <strong>{item.name}</strong>
              <span className="ai-sub"> · {item.date_label}</span>
            </div>
            <p className="ai-summary">{item.summary}</p>
            {item.past?.length > 0 && <p className="ai-sub">{item.past[0].text}</p>}
            <p className="ai-question">{item.question}</p>
            {item.checks?.length > 0 && (
              <ul className="ai-checks">
                {item.checks.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            )}
            <div className="ai-actions">
              {item.kind === "category" ? (
                <Link className={index === 0 ? "button" : "button secondary"} to={`/category/${encodeURIComponent(item.category)}?date=${item.date}`}>
                  기록하기
                </Link>
              ) : (
                <button type="button" className={index === 0 ? "button" : "button secondary"} onClick={() => setOpenNote(openNote === item.id ? null : item.id)}>
                  기록하기
                </button>
              )}
              <button type="button" className="text-button" onClick={() => quick(item, "none")}>
                특이사항 없음
              </button>
              <button type="button" className="text-button" onClick={() => quick(item, "unknown")}>
                모르겠어요
              </button>
            </div>
            {openNote === item.id && (
              <NoteBox hintDate={item.date} hintCategory={item.kind === "category" ? item.category : STORE} onSaved={() => { setOpenNote(null); load(); onChanged?.(); }} onClose={() => setOpenNote(null)} />
            )}
          </li>
        ))}
      </ul>

      {!isAi && FIXED_NOTE[aiState] && <p className="ai-sub">{FIXED_NOTE[aiState]}</p>}
      {view.reason === "failed" && !FIXED_NOTE[aiState] && <p className="ai-sub">AI 설명을 만들지 못해 계산 결과로 보여드려요.</p>}

      {undo && (
        <p className="undo" role="status">
          기록했어요.{" "}
          <button type="button" className="text-button" onClick={undoRecord}>
            되돌리기
          </button>
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          저장하지 못했어요. 항목은 그대로 두었어요. 잠시 후 다시 눌러 주세요.
        </p>
      )}

      {aiState === "ready" || isAi ? (
        <div className="ai-free">
          {openNote === "free" ? (
            <NoteBox hintDate={view.date} onSaved={() => { setOpenNote(null); load(); onChanged?.(); }} onClose={() => setOpenNote(null)} />
          ) : (
            <button type="button" className="text-button" onClick={() => setOpenNote("free")}>
              한마디로 남기기
            </button>
          )}
        </div>
      ) : null}

      {isAi && view.items.length > 0 && !openNote && <FeedbackButtons kind="briefing" refId={view.date} />}
    </Card>
  );
}
