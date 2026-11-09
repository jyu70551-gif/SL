import { useEffect, useMemo, useState } from "react";
import { dateLabel, hourLabel } from "../format.js";

const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
const pad = (n) => String(n).padStart(2, "0");
const isoOf = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
const monthIndex = (iso) => {
  const [y, m] = iso.split("-").map(Number);
  return y * 12 + (m - 1);
};

function todayIso() {
  const now = new Date();
  return isoOf(now.getFullYear(), now.getMonth() + 1, now.getDate());
}

// 올려 둔 날짜를 달력으로 조회합니다. 기록 있는 날은 점과 연한 바탕, 선택한 날은 진한 보라, 오늘은 테두리로 구분하고,
// 날짜를 누르면 그날 올린 파일 이름과 집계 시각을 보여 줍니다.
export default function UploadCalendar({ uploads }) {
  const byDate = useMemo(() => new Map(uploads.map((u) => [u.date, u])), [uploads]);
  const newest = uploads.reduce((a, u) => (u.date > a ? u.date : a), uploads[0].date);
  const oldest = uploads.reduce((a, u) => (u.date < a ? u.date : a), uploads[0].date);
  const today = todayIso();
  const lastMonth = Math.max(monthIndex(newest), monthIndex(today));
  const firstMonth = monthIndex(oldest);

  const [shown, setShown] = useState(() => monthIndex(newest)); // 연*12 + (월-1)
  const [selected, setSelected] = useState("");

  // 새로 올려서 가장 최근 날짜가 바뀌면 그 달로 이동합니다.
  useEffect(() => {
    setShown(monthIndex(newest));
    setSelected("");
  }, [newest]);

  const year = Math.floor(shown / 12);
  const month = (shown % 12) + 1;
  const daysInMonth = new Date(year, month, 0).getDate();
  const offset = (new Date(year, month - 1, 1).getDay() + 6) % 7; // 월요일이 첫 칸
  const cells = [...Array(offset).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];
  const uploadedThisMonth = Array.from({ length: daysInMonth }, (_, i) => isoOf(year, month, i + 1)).filter((iso) => byDate.has(iso)).length;
  const chosen = selected ? byDate.get(selected) : null;

  return (
    <div className="ucal">
      <div className="ucal-head">
        <button type="button" className="ucal-nav" onClick={() => setShown(shown - 1)} disabled={shown <= firstMonth} aria-label="이전 달">
          ‹
        </button>
        <div className="ucal-title-box">
          <strong className="ucal-title" aria-live="polite">
            {year}년 {month}월
          </strong>
          <span className="muted ucal-month-count">
            {uploadedThisMonth > 0 ? `${uploadedThisMonth}일 올림` : "올린 날 없음"}
            {shown !== monthIndex(newest) && (
              <button type="button" className="text-button ucal-latest" onClick={() => setShown(monthIndex(newest))}>
                가장 최근 달로
              </button>
            )}
          </span>
        </div>
        <button type="button" className="ucal-nav" onClick={() => setShown(shown + 1)} disabled={shown >= lastMonth} aria-label="다음 달">
          ›
        </button>
      </div>

      <div className="ucal-grid" role="group" aria-label={`${year}년 ${month}월 올려 둔 날짜`}>
        {WEEKDAYS.map((w) => (
          <span key={w} className="ucal-weekday">
            {w}
          </span>
        ))}
        {cells.map((day, i) => {
          if (day === null) return <span key={`blank-${i}`} className="ucal-blank" />;
          const iso = isoOf(year, month, day);
          const upload = byDate.get(iso);
          const classes = `ucal-day${upload ? " has-data" : ""}${iso === today ? " is-today" : ""}${iso === selected ? " is-selected" : ""}`;
          const label = `${month}월 ${day}일${iso === today ? " (오늘)" : ""}, ${upload ? `${hourLabel(upload.cutoff_hour)}까지 올림` : "올린 기록 없음"}`;
          return upload ? (
            <button key={iso} type="button" className={classes} aria-label={label} aria-pressed={iso === selected} onClick={() => setSelected(iso === selected ? "" : iso)}>
              <span>{day}</span>
              <span className="ucal-dot" aria-hidden="true" />
            </button>
          ) : (
            <span key={iso} className={classes}>
              <span>{day}</span>
            </span>
          );
        })}
      </div>

      <ul className="ucal-legend" aria-label="달력 표시 설명">
        <li>
          <span className="ucal-key has-data">
            <span className="ucal-dot" />
          </span>
          기록 있는 날
        </li>
        <li>
          <span className="ucal-key is-selected">
            <span className="ucal-dot" />
          </span>
          선택한 날
        </li>
        <li>
          <span className="ucal-key is-today" />
          오늘
        </li>
      </ul>

      <div className="ucal-detail" role="status">
        {chosen ? (
          <dl>
            <div>
              <dt>날짜</dt>
              <dd>{dateLabel(selected)}</dd>
            </div>
            <div>
              <dt>파일명</dt>
              <dd className="ucal-file">{chosen.filename || "기록 없음"}</dd>
            </div>
            <div>
              <dt>집계 시각</dt>
              <dd>{hourLabel(chosen.cutoff_hour)}까지</dd>
            </div>
          </dl>
        ) : (
          <p className="muted">기록 있는 날짜를 누르면 파일명과 집계 시각이 보여요.</p>
        )}
      </div>
    </div>
  );
}
