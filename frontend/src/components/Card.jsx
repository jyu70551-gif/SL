import { useState } from "react";

// 홈과 상세 화면의 한 영역. 안쪽에 카드를 또 만들지 않고 여백과 얇은 구분선으로 나눕니다.
export function Card({ title, aside, keyMark = false, children }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2 className={keyMark ? "card-title key" : "card-title"}>{title}</h2>
        {aside && <span className="card-aside">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

// 데이터가 더 쌓여야 보여줄 수 있는 부분의 안내. 오류가 아니라 정상 상태입니다.
export function NeedMore({ comparison, weekday, scopeText }) {
  const { weeks_used: used, min_days: min, needed_more: more, excluded_other_hour: excluded } = comparison;
  return (
    <div className="need-more">
      <span>
        <strong>데이터가 더 필요해요.</strong> {scopeText ?? `같은 ${weekday}요일, 같은 시각까지의 매출이`} {min}번 쌓이면
        평소와 비교해 드려요. ({used}/{min}, {more}번 더 필요)
      </span>
      <div className="progress-dots" aria-hidden="true">
        {Array.from({ length: min }, (_, i) => (
          <span key={i} className={i < used ? "on" : ""} />
        ))}
      </div>
      {excluded > 0 && (
        <span>마감 시각이 달라서 비교에서 뺀 같은 요일이 {excluded}번 있어요.</span>
      )}
    </div>
  );
}

// 비교 기준을 짧게 보여주고, 자세한 설명은 버튼을 눌렀을 때만 펼칩니다.
export function BasisToggle({ summary, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="basis">
      <div className="basis-row">
        <span className="basis-summary">{summary}</span>
        <button type="button" className="text-button" aria-expanded={open} onClick={() => setOpen(!open)}>
          비교 기준 {open ? "▴" : "▾"}
        </button>
      </div>
      {open && <div className="basis-panel">{children}</div>}
    </div>
  );
}
