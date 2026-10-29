import { count, won } from "../format.js";

// 평소와의 차이를 문장으로: "같은 수요일 기준보다 30,000원 많아요" + 증가율은 작고 약하게.
// 증가·감소는 좋고 나쁨이 아니므로 기본은 색 없이 ▲▼ 기호와 문구로만 구분합니다.
// directional이면 매출 변화 방향을 색으로도 보여줍니다: 증가 민트, 감소 코랄, 같음 회색.
// (이 색은 방향만 뜻하며 정상·주의 판정 색과 다릅니다. 색 없이도 ▲▼—와 문구로 읽힙니다)
export function DiffLine({ diff, pct, unit = "won", basis = "비교 기준", directional = false }) {
  if (diff === null || diff === undefined) return null;
  const fmt = unit === "count" ? count : won;
  const arrow = diff > 0 ? "▲" : diff < 0 ? "▼" : "—";
  const tone = !directional ? "" : diff > 0 ? " rise" : diff < 0 ? " fall" : " same";
  const pctText =
    pct === null || pct === undefined
      ? null
      : `${pct > 0 ? "+" : pct < 0 ? "−" : ""}${Math.abs(pct).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`;
  return (
    <>
      <p className={`diff-line${tone}`}>
        <span className="diff-icon" aria-hidden="true">
          {arrow}
        </span>
        {diff === 0 ? `${basis}과 같아요` : `${basis}보다 ${fmt(Math.abs(diff))} ${diff > 0 ? "많아요" : "적어요"}`}
      </p>
      {pctText && <p className="pct">{pctText}</p>}
    </>
  );
}
