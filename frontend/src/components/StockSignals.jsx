import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";
import { longDate, monthDay } from "../format.js";

// 집중 관리 식품군: 상품별 소진율·폐기율과 발주 점검 신호. (docs/stock.md)
// 점주의 점검 목록처럼 상품마다 세 줄만 보입니다: 확인할 이유 → 소진율·폐기율 → 다음 행동.
// 기준 설명(몇 회를 합산했는지, 날짜별 수량·품절 시각, 판정 기준)은 "근거 보기" 안에 접어 둡니다.
// 신호와 숫자는 모두 서버가 계산한 것이고 여기서는 보여 주기만 합니다. 입출고 자료가 없으면 아무것도 그리지 않습니다.
// "행사 없는 날"은 행사(1+1 등)를 하지 않은 날입니다. 공휴일·장날은 빼지 않았으니 '평소'라고 쓰지 않습니다.
const SIGNAL = {
  increase_review: { text: "증량 검토", guessed: "품절 확인", tone: "warn" },
  decrease_review: { text: "폐기 점검", tone: "warn" },
  promo_only: { text: "행사 비교", tone: "note" },
  balanced: { text: "참고", tone: "ok" },
  none: { text: "신호 없음", tone: "none" },
  insufficient: { text: "자료 부족", tone: "none" },
};
// 근거 보기 안의 판정 기준은 그 상품의 신호에 해당하는 한 줄만 보여 줍니다.
const CRITERIA = {
  increase_review: (p) =>
    `기준: 소진율 ${Math.round(p.high_sell_through * 100)}% 이상이 ${p.window}회 중 ${p.high_days}회 이상 + 일찍 품절 ${p.stockout_days}회 이상 + 폐기 ${Math.round(p.max_waste_rate * 100)}% 이하`,
  decrease_review: (p) =>
    `기준: 폐기 ${Math.round(p.waste_rate * 100)}% 이상이 ${p.window}회 중 ${p.waste_days}회 이상 + 소진율 ${Math.round(p.low_sell_through * 100)}% 이하`,
};
const PRIORITY = ["increase_review", "decrease_review", "promo_only"];
const TOP = 3; // 처음에는 확인할 상품을 이만큼만 보여 줍니다

const pct = (v) => (v == null ? "—" : `${v}%`);
const estimated = (item) => item.stockout_basis?.includes("추정");

// 확인할 이유 (한 줄, 크게)
function reason(item, params) {
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
function action(item) {
  if (item.signal === "increase_review") {
    return estimated(item) ? "품절 시각을 기록해서 일찍 품절되는지 먼저 확인해 보세요." : "소량 늘린 뒤 판매·폐기가 어떻게 달라지는지 확인해 보세요.";
  }
  if (item.signal === "decrease_review") return "발주 수량뿐 아니라 진열·상품 구성도 함께 살펴보세요.";
  if (item.signal === "promo_only") return "행사 종료 후에는 행사 없는 기간의 판매 기록을 참고해 보세요.";
  return null;
}

function DayRows({ days }) {
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

function Product({ item, params }) {
  const [open, setOpen] = useState(false);
  const sig = SIGNAL[item.signal] ?? SIGNAL.none;
  const next = action(item);
  const toggle = () => setOpen((v) => !v);
  // 상품명·이유 등 행의 아무 곳을 눌러도 상세를 열고 닫습니다. 안쪽 버튼·링크를 누른 클릭은 그 버튼이 처리하므로 여기서는 건너뜁니다
  // (그렇지 않으면 버튼 클릭이 행까지 올라와서 열었다 바로 닫히는 식으로 두 번 실행됩니다).
  const onRowClick = (e) => {
    if (e.target.closest("button, a")) return;
    toggle();
  };
  const judged = item.window.days >= params.window;
  return (
    <li className="stock-item">
      <div className="stock-row" onClick={onRowClick}>
        <strong className="stock-name">{item.name}</strong>
        <div className="stock-why">
          <p className="stock-reason">{reason(item, params)}</p>
        </div>
        <span className="stock-rate stock-sell">
          <span className="stock-rate-label">소진율</span>
          <strong>{judged ? pct(item.window.sell_through_pct) : "—"}</strong>
        </span>
        <span className="stock-rate stock-waste">
          <span className="stock-rate-label">폐기율</span>
          <strong>{judged ? pct(item.window.waste_pct) : "—"}</strong>
        </span>
        <span className={`stock-badge ${sig.tone}`}>{item.signal === "increase_review" && estimated(item) ? sig.guessed : sig.text}</span>
        <button type="button" className="text-button stock-more" aria-expanded={open} onClick={toggle}>
          상세 보기 {open ? "▴" : "▾"}
        </button>
      </div>
      {open && (
        <div className="basis-panel">
          {next && <p className="stock-action">권장 행동: {next}</p>}
          {item.selling_now && <p>오늘 분은 판매 중이에요(지금까지 {item.selling_now.sold}개). 끝난 뒤부터 반영돼요.</p>}
          <p>
            행사 없이 판매를 마친 최근 {item.window.days}회: {item.window.sold}/{item.window.available} = 소진율 {pct(item.window.sell_through_pct)}, 폐기{" "}
            {item.window.discarded}개
          </p>
          <DayRows days={item.window_days} />
          {item.promo_window.days > 0 && (
            <>
              <p>
                행사 중 {item.promo_window.days}회: 소진율 {pct(item.promo_window.sell_through_pct)}, 폐기율 {pct(item.promo_window.waste_pct)}. 행사 때문이라고
                확정할 수는 없어요.
              </p>
              <DayRows days={item.promo_days} />
            </>
          )}
          {CRITERIA[item.signal] && <p className="stock-criteria">{CRITERIA[item.signal](params)} (검증 전 초기값)</p>}
          {estimated(item) && <p>품절 시각 기록이 없어 &lsquo;다 팔렸는지&rsquo;로 추정했어요.</p>}
          {item.carryover && <p>이월 재고가 있어서 합산 소진율이 실제보다 낮게 보일 수 있어요.</p>}
          {item.dropped_mismatch > 0 && <p>재고 수량이 안 맞는 기록 {item.dropped_mismatch}건은 뺐어요.</p>}
        </div>
      )}
    </li>
  );
}

export default function StockSignals() {
  const [data, setData] = useState(null);
  const [more, setMore] = useState(false);

  useEffect(() => {
    let alive = true;
    request("/api/stock/summary")
      .then((d) => alive && setData(d))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  if (!data || data.status !== "ready") return null;
  const flagged = data.products.filter((p) => PRIORITY.includes(p.signal));
  const shown = flagged.slice(0, TOP);
  const rest = [...flagged.slice(TOP), ...data.products.filter((p) => !PRIORITY.includes(p.signal))];
  return (
    <Card title="식품 발주 점검" aside={data.demo ? <span className="stock-demo">시연용 상품 데이터</span> : null}>
      <p className="card-note">행사 없이 판매를 마친 기록 기준 · {longDate(data.date)}까지</p>
      {shown.length === 0 && <p className="card-note">지금 확인할 신호는 없어요.</p>}
      <div className="stock-cols" aria-hidden="true">
        <span>상품</span>
        <span>확인할 이유</span>
        <span>소진율</span>
        <span>폐기율</span>
        <span>상태</span>
        <span>상세</span>
      </div>
      <ul className="stock-list">
        {shown.map((p) => (
          <Product key={p.product} item={p} params={data.params} />
        ))}
      </ul>
      {rest.length > 0 && (
        <>
          <button type="button" className="text-button" aria-expanded={more} onClick={() => setMore(!more)}>
            다른 상품 {rest.length}개 {more ? "접기 ▴" : "보기 ▾"}
          </button>
          {more && (
            <ul className="stock-list">
              {rest.map((p) => (
                <Product key={p.product} item={p} params={data.params} />
              ))}
            </ul>
          )}
        </>
      )}
      <p className="card-note">품절이 났다면 실제 수요는 판매량보다 클 수 있어요.</p>
    </Card>
  );
}
