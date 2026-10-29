import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, request } from "../api.js";
import { Card, NeedMore } from "../components/Card.jsx";
import { count, dateLabel, describeChange, hourLabel, won } from "../format.js";

function Delta({ pct }) {
  const { text, tone } = describeChange(pct);
  return <span className={`delta ${tone}`}>{text}</span>;
}

// 오늘 값과 평소 값을 나란히 놓고 길이로 비교합니다.
function CompareRow({ label, todayText, baselineText, pct, todayValue, baselineValue }) {
  // 막대 = 오늘, 흰 눈금 = 평소. 오늘이 평소보다 크든 작든 차이가 눈에 보이도록 여유를 둡니다.
  const top = Math.max(todayValue, baselineValue, 1) * 1.15;
  return (
    <div className="compare-row">
      <div className="compare-line">
        <span>{label}</span>
        <Delta pct={pct} />
      </div>
      <div className="meter" role="img" aria-label={`오늘 ${todayText}, 평소 ${baselineText}`}>
        <div className="meter-fill" style={{ width: `${(todayValue / top) * 100}%` }} />
        <div className="meter-tick" style={{ left: `${(baselineValue / top) * 100}%` }} />
      </div>
      <div className="compare-line">
        <span className="muted">오늘 {todayText}</span>
        <span className="muted">평소 {baselineText}</span>
      </div>
    </div>
  );
}

function TotalCard({ data }) {
  const { today, comparison, weekday, cutoff_hour: hour } = data;
  return (
    <Card
      title="오늘 총매출·판매수량"
      chip={`${hourLabel(hour)}까지`}
      chipTone="accent"
      keyMark
      footer={`${dateLabel(data.date)} · ${hourLabel(hour)}까지의 매출`}
    >
      <div className="kpi-row">
        <div className="kpi">
          <div className="kpi-label">총매출</div>
          <div className="kpi-value">{won(today.total_amount)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">총 판매수량</div>
          <div className="kpi-value">{count(today.total_quantity)}</div>
        </div>
      </div>

      <div className="compare">
        <p className="compare-title">평소 {weekday}요일과 비교</p>
        {comparison.status === "ready" ? (
          <>
            <CompareRow
              label="총매출"
              todayText={won(today.total_amount)}
              baselineText={won(comparison.baseline_amount)}
              pct={comparison.amount_change_pct}
              todayValue={today.total_amount}
              baselineValue={comparison.baseline_amount}
            />
            <CompareRow
              label="총 판매수량"
              todayText={count(today.total_quantity)}
              baselineText={count(comparison.baseline_quantity)}
              pct={comparison.quantity_change_pct}
              todayValue={today.total_quantity}
              baselineValue={comparison.baseline_quantity}
            />
            <p className="card-note">최근 같은 요일 {comparison.weeks_used}번의 평균과 비교했어요.</p>
          </>
        ) : (
          <NeedMore comparison={comparison} weekday={weekday} />
        )}
      </div>
    </Card>
  );
}

const VERDICT = {
  high: { text: "평소보다 많음", tone: "warn" },
  normal: { text: "평소 수준", tone: "ok" },
  low: { text: "평소보다 적음", tone: "warn" },
};

function RangeBar({ item }) {
  const top = Math.max(item.range_max, item.today_quantity, 1) * 1.25;
  const pct = (n) => `${(n / top) * 100}%`;
  return (
    <div
      className="range-bar"
      role="img"
      aria-label={`오늘 ${count(item.today_quantity)}, 평소 범위 ${item.range_min}~${item.range_max}개`}
    >
      <div
        className="range-band"
        style={{ left: pct(item.range_min), width: `${((item.range_max - item.range_min) / top) * 100 || 1}%` }}
      />
      <div className="range-marker" style={{ left: pct(item.today_quantity) }} />
    </div>
  );
}

function InstantFoodCard({ data }) {
  const hour = data.cutoff_hour;
  const first = data.instant_food[0];
  return (
    <Card
      title="즉석식품 요약"
      chip={`${hourLabel(hour)}까지`}
      chipTone="accent"
      footer="상품별이 아니라 대분류(간편식사·즉석조리) 기준이에요."
    >
      <div className="food-list">
        {data.instant_food.map((item) => {
          const verdict = VERDICT[item.verdict];
          return (
            <div className="food-row" key={item.category}>
              <div className="food-top">
                <span className="food-name">{item.category}</span>
                <span className="food-qty">{count(item.today_quantity)}</span>
              </div>
              {item.status === "ready" ? (
                <>
                  <RangeBar item={item} />
                  <div className="compare-line">
                    <span className="muted">
                      평소 {item.range_min}~{item.range_max}개
                    </span>
                    <span className={`chip ${verdict.tone}`}>{verdict.text}</span>
                  </div>
                </>
              ) : null}
            </div>
          );
        })}
      </div>
      {first.status !== "ready" && (
        <div style={{ marginTop: 12 }}>
          <NeedMore comparison={first} weekday={data.weekday} />
        </div>
      )}
    </Card>
  );
}

// 아직 만들지 않은 카드. 자리만 잡아 둡니다.
function ComingSoonCard({ title }) {
  return (
    <Card title={title} chip="준비 중">
      <p className="card-note">아직 준비 중이에요.</p>
    </Card>
  );
}

function EmptyCard() {
  return (
    <Card title="아직 올린 파일이 없어요">
      <p className="card-note">마감 후 매출 파일을 올리면 오늘 매출과 평소와의 비교를 보여 드려요.</p>
      <div style={{ marginTop: 12 }}>
        <Link to="/upload" className="button">
          파일 올리러 가기
        </Link>
      </div>
    </Card>
  );
}

export default function Home() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setData(await request("/api/home/summary"));
    } catch (e) {
      if (!(e instanceof ApiError && e.detail?.code === "unauthorized")) setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section>
      <div className="page-head">
        <h1 className="page-title">홈</h1>
        {data?.has_data && <span className="page-sub">{dateLabel(data.date)}</span>}
      </div>

      {failed && (
        <Card title="숫자를 불러오지 못했어요">
          <p className="card-note">서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.</p>
          <div style={{ marginTop: 12 }}>
            <button type="button" className="button secondary" onClick={load}>
              다시 시도
            </button>
          </div>
        </Card>
      )}

      {!failed && data === null && <p className="empty-note">불러오는 중…</p>}

      {data && !data.has_data && <EmptyCard />}

      {data?.has_data && (
        <>
          <ComingSoonCard title="확인이 필요한 대분류" />
          <TotalCard data={data} />
          <InstantFoodCard data={data} />
          <ComingSoonCard title="내일 예상 매출" />
        </>
      )}
    </section>
  );
}
