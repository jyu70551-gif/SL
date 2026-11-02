import { useRef, useState } from "react";
import { request } from "../api.js";
import { categoryLabel, REASONS, toggleReason } from "../reasons.js";
import { shortDate } from "../format.js";
import FeedbackButtons from "./FeedbackButtons.jsx";

// AI가 정리한 초안을 점주가 확인·수정하고 저장하는 곳. [저장]을 눌러야만 기록됩니다.
export default function DraftPreview({ draft, candidates, onSaved, onCancel }) {
  const [category, setCategory] = useState(draft.category);
  const [date, setDate] = useState(draft.date ?? candidates.dates[0]);
  const [reasons, setReasons] = useState(draft.situations);
  const [detail, setDetail] = useState(draft.detail);
  const [timeHint, setTimeHint] = useState(draft.time_hint ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const initial = useRef(JSON.stringify([draft.category, draft.date ?? candidates.dates[0], draft.situations, draft.detail, draft.time_hint ?? ""]));

  const edited = JSON.stringify([category, date, reasons, detail, timeHint]) !== initial.current;

  async function save() {
    setBusy(true);
    setError(false);
    try {
      await request("/api/anomalies/review", {
        method: "POST",
        body: {
          category,
          dates: [date],
          reasons,
          memo: detail,
          source: "ai",
          raw_text: draft.raw_text,
          time_hint: timeHint,
          ai_edited: edited,
        },
      });
      onSaved();
    } catch {
      setError(true); // 저장되지 않았으면 초안을 그대로 둡니다
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="draft">
      <p className="ai-sub">AI가 정리했어요. 확인한 뒤 저장돼요. 통계로 확인된 원인은 아니에요.</p>
      <dl className="draft-list">
        <div>
          <dt>관련 분류</dt>
          <dd>
            <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="관련 분류">
              {candidates.categories.map((c) => (
                <option key={c} value={c}>
                  {categoryLabel(c)}
                </option>
              ))}
            </select>
          </dd>
        </div>
        <div>
          <dt>날짜</dt>
          <dd>
            <select value={date} onChange={(e) => setDate(e.target.value)} aria-label="날짜">
              {candidates.dates.map((d) => (
                <option key={d} value={d}>
                  {shortDate(d)}
                </option>
              ))}
            </select>
          </dd>
        </div>
        <div className="stack">
          <dt>운영 상황</dt>
          <dd>
            {REASONS.map(([key, label]) => (
              <label key={key} className="check-row">
                <input type="checkbox" checked={reasons.includes(key)} onChange={() => setReasons(toggleReason(reasons, key))} />
                <span>{label}</span>
              </label>
            ))}
          </dd>
        </div>
        <div>
          <dt>시각</dt>
          <dd>
            <input
              className="draft-input"
              type="text"
              maxLength={30}
              value={timeHint}
              onChange={(e) => setTimeHint(e.target.value)}
              placeholder="예: 오전 7시경"
              aria-label="시각"
            />
          </dd>
        </div>
        <div className="stack">
          <dt>정리한 내용</dt>
          <dd>
            <textarea className="memo-input" rows={2} maxLength={300} value={detail} onChange={(e) => setDetail(e.target.value)} aria-label="정리한 내용" />
          </dd>
        </div>
        <div className="stack">
          <dt>근거 (점주 입력)</dt>
          <dd className="quote">&ldquo;{draft.raw_text}&rdquo;</dd>
        </div>
      </dl>

      <div className="button-row">
        <button type="button" className="button" disabled={busy || reasons.length === 0 || !category} onClick={save}>
          저장
        </button>
        <button type="button" className="button secondary" disabled={busy} onClick={onCancel}>
          취소
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          저장하지 못했어요. 내용은 그대로 두었어요. 잠시 후 다시 눌러 주세요.
        </p>
      )}
      <FeedbackButtons kind="draft" refId={`${category}|${date}`} />
    </div>
  );
}
