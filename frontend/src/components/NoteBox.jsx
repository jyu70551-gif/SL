import { useState } from "react";
import { ApiError, request } from "../api.js";
import DraftPreview from "./DraftPreview.jsx";

const MAX_CHARS = 500;
const UNAVAILABLE = {
  off: "AI 기능이 꺼져 있어요.",
  no_key: "AI 연결 키가 아직 없어요.",
  limit: "이번 달 AI 사용 한도에 도달했어요.",
  degraded: "AI 연결이 불안정해서 잠시 쉬고 있어요.",
  key_invalid: "AI 연결 키가 올바르지 않아요.",
  error: "AI가 응답하지 못했어요.",
};

// 점주가 말하듯 한마디를 쓰면 AI가 저장용 초안으로 정리합니다. 이 상자는 저장하지 않고, 확인 화면(DraftPreview)에서 저장합니다.
export default function NoteBox({ hintDate, hintCategory, onSaved, onClose }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState(null); // 서버가 돌려준 초안 응답
  const [chosen, setChosen] = useState({}); // 되묻기에서 점주가 고른 값

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setResult(null);
    setChosen({});
    try {
      const body = await request("/api/ai/notes/draft", {
        method: "POST",
        body: { text, date: hintDate ?? null, category: hintCategory ?? null },
      });
      if (body.status === "unavailable") {
        setMessage(`${UNAVAILABLE[body.state] ?? "AI를 쓸 수 없어요."} 항목을 눌러 직접 기록할 수 있어요.`);
      } else if (body.status === "unrelated") {
        setMessage("운영 상황과 관련 없는 글 같아요. 매출이나 입고, 행사 같은 이야기를 적어 주세요.");
      } else {
        setResult(body);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setMessage("잠시 후에 다시 시도해 주세요. (1분에 6번까지 정리할 수 있어요)");
      else if (e instanceof ApiError && e.status === 422) setMessage(`글은 1자 이상 ${e.detail?.max_chars ?? MAX_CHARS}자 이하로 적어 주세요.`);
      else setMessage("정리하지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  const draft = result?.draft ? { ...result.draft, ...chosen } : null;
  const question = result?.question;
  const unresolved = question && !chosen[question.kind];

  return (
    <div className="note-box">
      {!result && (
        <form onSubmit={submit}>
          <label className="memo-label" htmlFor="note-text">
            한마디로 남기기
          </label>
          <textarea
            id="note-text"
            className="memo-input"
            rows={3}
            maxLength={MAX_CHARS}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="예: 오늘 김밥 입고가 늦었고 7시쯤 샌드위치가 다 나갔어."
          />
          <p className="ai-sub">
            쓰신 글은 정리를 위해 OpenAI로 보내져요. 직원·손님 이름은 쓰지 마세요. ({text.length}/{MAX_CHARS})
          </p>
          <div className="button-row">
            <button type="submit" className="button secondary" disabled={busy || !text.trim()}>
              {busy ? "정리하고 있어요…" : "정리하기"}
            </button>
            {onClose && (
              <button type="button" className="button secondary" onClick={onClose}>
                닫기
              </button>
            )}
          </div>
          {message && (
            <p className="ai-sub" role="status">
              {message}
            </p>
          )}
        </form>
      )}

      {result && unresolved && (
        <div className="clarify">
          <p className="clarify-q">{question.text}</p>
          <div className="option-row">
            {question.options.map((option) => (
              <button
                key={option.value}
                type="button"
                className="button secondary"
                onClick={() => setChosen({ ...chosen, [question.kind]: option.value })}
              >
                {option.label}
              </button>
            ))}
          </div>
          <button type="button" className="text-button" onClick={() => setResult(null)}>
            다시 쓰기
          </button>
        </div>
      )}

      {result && !unresolved && draft && (
        <DraftPreview
          key={`${draft.category}|${draft.date}`}
          draft={draft}
          candidates={result.candidates}
          onSaved={() => {
            setResult(null);
            setText("");
            onSaved?.();
          }}
          onCancel={() => setResult(null)}
        />
      )}
    </div>
  );
}
