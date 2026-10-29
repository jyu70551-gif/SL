// 화면에 보여줄 글자를 만드는 도구들

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

export function hourLabel(hour) {
  if (hour === 0) return "오전 12시(자정)";
  if (hour < 12) return `오전 ${hour}시`;
  if (hour === 12) return "오후 12시(정오)";
  return `오후 ${hour - 12}시`;
}

export function dateLabel(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = WEEKDAYS[new Date(y, m - 1, d).getDay()];
  return `${y}년 ${m}월 ${d}일 (${weekday})`;
}

export function won(n) {
  return `${Math.round(n).toLocaleString("ko-KR")}원`;
}

export function count(n) {
  return `${Math.round(n).toLocaleString("ko-KR")}개`;
}

// 변화율을 ▲▼ 기호와 부호로 보여줍니다. (색만으로 구분하지 않습니다)
export function describeChange(pct) {
  if (pct === null || pct === undefined) return { text: "비교 불가", tone: "flat" };
  if (pct === 0) return { text: "변화 없음", tone: "flat" };
  const arrow = pct > 0 ? "▲" : "▼";
  const sign = pct > 0 ? "+" : "−";
  return {
    text: `${arrow} ${sign}${Math.abs(pct).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`,
    tone: pct > 0 ? "up" : "down",
  };
}

// 그래프 눈금처럼 좁은 곳에 쓰는 짧은 금액 (예: 15만, 8,000)
export function shortWon(n) {
  if (n >= 10000) return `${Math.round(n / 10000).toLocaleString("ko-KR")}만`;
  return Math.round(n).toLocaleString("ko-KR");
}

export function monthDay(iso) {
  const [, m, d] = iso.split("-").map(Number);
  return `${m}/${d}`;
}

// "2월 25일(수)" 처럼 연도를 뺀 짧은 날짜
export function shortDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = WEEKDAYS[new Date(y, m - 1, d).getDay()];
  return `${m}월 ${d}일(${weekday})`;
}

// 그래프 세로축 눈금 글자. 눈금 위치의 실제 값과 글자가 정확히 같아야 합니다. (예: 10000 → "1만", 15000 → "1.5만", 5000 → "5,000")
export function axisLabel(v) {
  if (v === 0) return "0";
  if (v >= 10000) return `${Number((v / 10000).toFixed(2)).toLocaleString("ko-KR")}만`;
  return v.toLocaleString("ko-KR");
}

// 최대값을 덮는, 눈금 간격이 깔끔한 세로축 (간격은 1·2·2.5·5 × 10의 거듭제곱)
export function niceAxis(max) {
  const raw = Math.max(max, 1) / 3;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw);
  const top = Math.ceil(Math.max(max, 1) / step) * step;
  const ticks = [];
  for (let v = 0; v <= top + step / 1000; v += step) ticks.push(Math.round(v));
  return { top, ticks };
}

// 집계 시각으로 부르는 말: "8시까지"는 아침, "22시까지"는 밤
export function periodWord(hour) {
  if (hour >= 5 && hour <= 11) return "아침";
  if (hour >= 12 && hour <= 17) return "낮";
  if (hour >= 18 && hour <= 21) return "저녁";
  return "밤";
}

// "2026년 2월 25일 수요일"
export function longDateLabel(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = ["일", "월", "화", "수", "목", "금", "토"][new Date(y, m - 1, d).getDay()];
  return `${y}년 ${m}월 ${d}일 ${weekday}요일`;
}

// 날짜 목록의 범위: 하루면 "2/18", 여러 날이면 "12/23 ~ 2/24"
export function rangeText(isoDates) {
  if (!isoDates.length) return "";
  const first = monthDay(isoDates[0]);
  const last = monthDay(isoDates[isoDates.length - 1]);
  return first === last ? first : `${first} ~ ${last}`;
}
