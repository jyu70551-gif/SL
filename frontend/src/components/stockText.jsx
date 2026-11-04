import { monthDay } from "../format.js";

// 식품 발주 점검(StockSignals)과 AI 점검 내용 패널이 함께 쓰는 문구입니다. 신호와 숫자는 서버가 계산한 값이고 여기서는 글로 풀어 쓰기만 합니다.
// "행사 없는 날"은 행사(1+1 등)를 하지 않은 날입니다. 공휴일·장날은 빼지 않았으니 '평소'라고 쓰지 않습니다.
export const SIGNAL = {
  increase_review: { text: "증량 검토", guessed: "품절 확인", tone: "warn" },
  decrease_review: { text: "폐기 점검", tone: "warn" },
  promo_only: { text: "행사 비교", tone: "note" },
  balanced: { text: "참고", tone: "ok" },
  none: { text: "신호 없음", tone: "none" },
  insufficient: { text: "자료 부족", tone: "none" },
};
// 근거 보기 안의 판정 기준은 그 상품의 신호에 해당하는 한 줄만 보여 줍니다.
export const CRITERIA = {
  increase_review: (p) =>
    `기준: 소진율 ${Math.round(p.high_sell_through * 100)}% 이상이 ${p.window}회 중 ${p.high_days}회 이상 + 일찍 품절 ${p.stockout_days}회 이상 + 폐기 ${Math.round(p.max_waste_rate * 100)}% 이하`,
  decrease_review: (p) =>
    `기준: 폐기 ${Math.round(p.waste_rate * 100)}% 이상이 ${p.window}회 중 ${p.waste_days}회 이상 + 소진율 ${Math.round(p.low_sell_through * 100)}% 이하`,
};

export const pct = (v) => (v == null ? "—" : `${v}%`);
export const estimated = (item) => item.stockout_basis?.includes("추정");

// 확인할 이유 (한 줄, 크게)
export function reason(item, params) {
  const n = item.window.days;
  const c = item.counts ?? {};
  switch (item.signal) {
    case "increase_review":
      if (estimated(item)) return `최근 ${n}회 중 다 팔린 날이 ${c.stockout_days}회예요. 일찍 품절됐는지는 품절 시각이 없어 알 수 없어요.`;
      return c.stockout_days === n ? `최근 ${n}회 모두 일찍 품절됐어요.` : `최근 ${n}회 중 ${c.stockout_days}회 일찍 품절됐어요.`;
    case "decrease_review":
      return `최근 ${n}회 중 ${c.waste_days}회 폐기가 ${Math.round(params.waste_rate * 100)}% 이상이었어요.`;
    case "promo_only":
      return `행사 중에는 소진율 ${pct(item.promo_window.sell_through_pct)}, 행사 없는 기간에는 ${pct(item.window.sell_through_pct)}였어요.`;
    case "balanced":
      return `일찍 품절된 적은 없었어요. 폐기 ${pct(item.window.waste_pct)}가 적절한지는 상품 이익과 비교해 보세요.`;
    case "insufficient":
      return `행사 없이 판매를 마친 기록이 ${n}회뿐이거나 수량이 적어서 판단하지 않아요.`;
    default:
      return "지금 눈에 띄는 신호는 없어요.";
  }
}

// 다음 행동 (한 줄)
export function action(item) {
  if (item.signal === "increase_review") {
    return estimated(item) ? "품절 시각을 기록해서 일찍 품절되는지 먼저 확인해 보세요." : "소량 늘린 뒤 판매·폐기가 어떻게 달라지는지 확인해 보세요.";
  }
  if (item.signal === "decrease_review") return "발주 수량뿐 아니라 진열·상품 구성도 함께 살펴보세요.";
  if (item.signal === "promo_only") return "행사 종료 후에는 행사 없는 기간의 판매 기록을 참고해 보세요.";
  return null;
}

export function DayRows({ days }) {
  if (!days?.length) return null;
  return (
    <ul className="stock-days">
      {days.map((d) => (
        <li key={d.day}>
          {monthDay(d.day)} · 판매 {d.sold}/{d.available} · 폐기 {d.discarded}
          {d.sold_out_hour != null && ` · 품절 ${d.sold_out_hour}시`}
        </li>
      ))}
    </ul>
  );
}
