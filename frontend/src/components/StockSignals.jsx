import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";
import { longDate } from "../format.js";
import { CRITERIA, DayRows, SIGNAL, action, estimated, pct, reason } from "./stockText.jsx";

// 집중 관리 식품군: 상품별 소진율·폐기율과 발주 점검 신호. (docs/stock.md)
// 점주의 점검 목록처럼 상품마다 세 줄만 보입니다: 확인할 이유 → 소진율·폐기율 → 다음 행동.
// 기준 설명(몇 회를 합산했는지, 날짜별 수량·품절 시각, 판정 기준)은 "근거 보기" 안에 접어 둡니다.
// 신호와 숫자는 모두 서버가 계산한 것이고 여기서는 보여 주기만 합니다. 입출고 자료가 없으면 아무것도 그리지 않습니다.
// "행사 없는 날"은 행사(1+1 등)를 하지 않은 날입니다. 공휴일·장날은 빼지 않았으니 '평소'라고 쓰지 않습니다.
const PRIORITY = ["increase_review", "decrease_review", "promo_only"];
const TOP = 3; // 처음에는 확인할 상품을 이만큼만 보여 줍니다

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
