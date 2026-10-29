import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, request } from "../api.js";
import AnomalyCard from "../components/AnomalyCard.jsx";
import { BasisToggle, Card, NeedMore } from "../components/Card.jsx";
import { DiffLine } from "../components/Change.jsx";
import { ArrowLink } from "../components/Icons.jsx";
import { count, dateLabel, hourLabel, monthDay, shortDate, won } from "../format.js";

// 영역 1. 매출 요약: 총매출(가장 크게) → 금액 차이 → 증가율(보조) → 판매 수량
function SalesSummary({ data }) {
  const { today, comparison, weekday } = data;
  const ready = comparison.status === "ready";
  const used = comparison.used_dates ?? [];
  const qtyDiff = ready ? today.total_quantity - comparison.baseline_quantity : null;
  // 비교 기준이 0원이면 증가율은 계산하지 않고 금액 차이만 보여줍니다.
  const zeroBase = ready && comparison.baseline_amount === 0;
  return (
    <Card title="매출 요약">
      <div className="headline">
        <div className="headline-label">총매출</div>
        <div className="headline-value">{won(today.total_amount)}</div>
        {ready ? (
          <DiffLine
            diff={today.total_amount - comparison.baseline_amount}
            pct={zeroBase ? null : comparison.amount_change_pct}
            basis={`같은 ${weekday}요일 기준`}
            directional
          />
        ) : (
          <p className="diff-line same">비교 자료가 부족해요</p>
        )}
      </div>
      <p className="quantity-line">
        판매 수량 <strong>{count(today.total_quantity)}</strong>
      </p>

      {ready ? (
        <BasisToggle summary={`최근 같은 ${weekday}요일 ${comparison.weeks_used}번의 평균`}>
          <p>
            {shortDate(data.date)} 이전, 같은 {weekday}요일이면서 같은 시각({hourLabel(data.cutoff_hour)})까지 집계한 최근{" "}
            {comparison.weeks_used}번{used.length > 0 && <> ({used.map(monthDay).join(", ")})</>}의 <strong>평균</strong>이에요.
          </p>
          <ul className="basis-list">
            <li>
              총매출 기준 {won(comparison.baseline_amount)} → 오늘 {won(today.total_amount)}
            </li>
            <li>
              판매 수량 기준 {count(comparison.baseline_quantity)} → 오늘 {count(today.total_quantity)} (
              {qtyDiff > 0 ? "+" : qtyDiff < 0 ? "−" : ""}
              {count(Math.abs(qtyDiff))})
            </li>
          </ul>
          {comparison.excluded_other_hour > 0 && (
            <p>마감 시각이 달라서 뺀 같은 요일이 {comparison.excluded_other_hour}번 있어요.</p>
          )}
        </BasisToggle>
      ) : (
        <NeedMore comparison={comparison} weekday={weekday} />
      )}
      <ArrowLink to="/sales">총매출 자세히 보기</ArrowLink>
    </Card>
  );
}

const VERDICT = {
  high: { text: "평소보다 많음", tone: "warn" },
  normal: { text: "평소 범위", tone: "ok" },
  low: { text: "평소보다 적음", tone: "warn" },
};

// 영역 3. 집중 관리 식품군: 분류 · 판매 수량 · 비교 범위 · 상태
function FocusFood({ data }) {
  const first = data.instant_food[0];
  const ready = first.status === "ready";
  return (
    <Card title="집중 관리 식품군">
      <div className="food-table" role="table" aria-label="집중 관리 식품군">
        <div className="food-row food-head" role="row">
          <span role="columnheader">분류</span>
          <span role="columnheader">판매 수량</span>
          <span role="columnheader">과거 관측 범위</span>
          <span role="columnheader">상태</span>
        </div>
        {data.instant_food.map((item) => {
          const verdict = item.status === "ready" ? VERDICT[item.verdict] : null;
          return (
            <div className="food-row" role="row" key={item.category}>
              <span className="food-name" role="cell">
                {item.category}
              </span>
              <span className="food-qty" role="cell">
                {count(item.today_quantity)}
              </span>
              <span className="food-range" role="cell">
                {verdict ? `${item.range_min}~${item.range_max}개` : "—"}
              </span>
              <span className={`verdict ${verdict ? verdict.tone : "none"}`} role="cell">
                {verdict ? verdict.text : "판단 자료 부족"}
              </span>
            </div>
          );
        })}
      </div>
      {ready ? (
        <p className="card-note">
          과거 관측 범위는 최근 같은 {data.weekday}요일 {first.weeks_used}번의 가장 적었던 값~가장 많았던 값이에요. 상품별이 아니라 대분류 기준이에요.
        </p>
      ) : (
        <NeedMore comparison={first} weekday={data.weekday} />
      )}
    </Card>
  );
}

function EmptyCard() {
  return (
    <Card title="아직 올린 파일이 없어요">
      <p className="card-note">마감 후 매출 파일을 올리면 오늘 매출과 평소와의 비교를 보여 드려요.</p>
      <Link to="/upload" className="button">
        파일 올리러 가기
      </Link>
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
      {/* 분석 날짜와 집계 시간은 맨 위에 한 번만 보여줍니다. */}
      <div className="page-head">
        <h1 className="page-title">홈</h1>
        {data?.has_data && (
          <p className="page-meta">
            {dateLabel(data.date)} · {hourLabel(data.cutoff_hour)}까지 집계
          </p>
        )}
      </div>

      {failed && (
        <Card title="숫자를 불러오지 못했어요">
          <p className="card-note">서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.</p>
          <button type="button" className="button secondary" onClick={load}>
            다시 시도
          </button>
        </Card>
      )}

      {!failed && data === null && <p className="empty-note">불러오는 중…</p>}

      {data && !data.has_data && <EmptyCard />}

      {data?.has_data && (
        <>
          <SalesSummary data={data} />
          <AnomalyCard weekday={data.weekday} />
          <FocusFood data={data} />
        </>
      )}
    </section>
  );
}
