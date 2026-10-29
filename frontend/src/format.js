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
