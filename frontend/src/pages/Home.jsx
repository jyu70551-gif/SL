import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, request } from "../api.js";
import AnomalyCard from "../components/AnomalyCard.jsx";
import { BasisToggle, Card, NeedMore } from "../components/Card.jsx";
import { DiffLine } from "../components/Change.jsx";
import ForecastCard from "../components/ForecastCard.jsx";
import { StreetScene } from "../components/StoreScene.jsx";
import SuggestCard from "../components/SuggestCard.jsx";
import { ArrowLink } from "../components/Icons.jsx";
import { count, hourLabel, isToday, longDate, monthDay, periodLabel, shortDate, won } from "../format.js";

// 영역 1. 매출 요약 띠: 이 화면의 질문은 "매출이 평소 기록과 비교해 어떤가?"입니다.
// 읽는 순서: 제목과 기준 날짜·집계 시각(한 번만) → 총매출과 판매 수량 → 비교 문장 → 확인할 변화 건수 → 자세히 보기·비교 기준
// 날짜·금액·건수·시각은 모두 실제 데이터에서 가져옵니다. 분석 날짜가 오늘이 아니면 "오늘"이라고 하지 않고 "기준일"이라고 합니다.
function TodayBand({ data, attention }) {
  const { today, comparison, weekday } = data;
  const [basisOpen, setBasisOpen] = useState(false);
  const ready = comparison.status === "ready";
  const used = comparison.used_dates ?? [];
  const qtyDiff = ready ? today.total_quantity - comparison.baseline_quantity : null;
  // 비교 기준이 0원이면 증가율은 계산하지 않고 금액 차이만 보여줍니다.
  const zeroBase = ready && comparison.baseline_amount === 0;
  const dayWord = isToday(data.date) ? "오늘" : "기준일";
  const earlier = attention ? attention.total - attention.today : 0;
  return (
    <section className="band" aria-labelledby="band-title">
      <div className="band-top">
        <h1 className="band-title" id="band-title">
          {periodLabel(data.cutoff_hour)} 매출 점검
        </h1>
        <p className="band-when">
          <span>
            {dayWord} · {longDate(data.date)}
          </span>
          <span>{hourLabel(data.cutoff_hour)}까지 집계</span>
        </p>
      </div>

      <div className="band-body">
        <div className="band-main">
          <div className="band-figure">
            <div className="band-row">
              <div className="band-value">{won(today.total_amount)}</div>
              <p className="band-qty">
                판매 수량 <strong>{count(today.total_quantity)}</strong>
              </p>
            </div>
            {ready ? (
              <div className="band-diff">
                <DiffLine
                  diff={today.total_amount - comparison.baseline_amount}
                  pct={zeroBase ? null : comparison.amount_change_pct}
                  basis={`같은 ${weekday}요일 기준`}
                  directional
                />
              </div>
            ) : (
              <p className="diff-line same">비교 자료가 부족해요</p>
            )}
          </div>

          {attention && (
            <a className="band-finding" href="#attention">
              {attention.total === 0 ? (
                <>
                  <span aria-hidden="true">✓ </span>지금 확인할 사항이 없어요
                </>
              ) : (
                <>
                  {attention.today > 0 && (
                    <span>
                      {isToday(data.date) ? "오늘 확인할 변화" : "기준일 변화"} <strong>{attention.today}건</strong>
                    </span>
                  )}
                  {attention.today > 0 && earlier > 0 && <span className="band-sep" aria-hidden="true"> · </span>}
                  {earlier > 0 && (
                    <span>
                      이전 미확인 <strong>{earlier}건</strong>
                    </span>
                  )}
                  <span aria-hidden="true"> ›</span>
                </>
              )}
            </a>
          )}

          <div className="band-links">
            <ArrowLink to="/sales">총매출 보기</ArrowLink>
            {ready && (
              <button type="button" className="text-button" aria-expanded={basisOpen} onClick={() => setBasisOpen(!basisOpen)}>
                비교 기준 {basisOpen ? "▴" : "▾"}
              </button>
            )}
          </div>
        </div>
        <StreetScene />
      </div>

      {ready && basisOpen && (
        <div className="basis-panel">
          <p>
            {shortDate(data.date)} 이전, 같은 {weekday}요일이면서 같은 시각({hourLabel(data.cutoff_hour)})까지 집계한 최근{" "}
            {comparison.weeks_used}번{used.length > 0 && <> ({used.map(monthDay).join(", ")})</>}의 <strong>평균</strong>이에요.
          </p>
          <ul className="basis-list">
            <li>
              총매출 기준 {won(comparison.baseline_amount)} → {dayWord} {won(today.total_amount)}
            </li>
            <li>
              판매 수량 기준 {count(comparison.baseline_quantity)} → {dayWord} {count(today.total_quantity)} (
              {qtyDiff > 0 ? "+" : qtyDiff < 0 ? "−" : ""}
              {count(Math.abs(qtyDiff))})
            </li>
          </ul>
          {comparison.excluded_other_hour > 0 && (
            <p>마감 시각이 달라서 뺀 같은 요일이 {comparison.excluded_other_hour}번 있어요.</p>
          )}
        </div>
      )}
      {!ready && <NeedMore comparison={comparison} weekday={weekday} />}
    </section>
  );
}

// 비교 범위는 "지난 기록의 가장 적었던 값~가장 많았던 값"이라서 '평소'나 '정상'이라고 하지 않고 '관측 범위'라고 말합니다.
const VERDICT = {
  high: { text: "관측 범위보다 많음", tone: "warn" },
  normal: { text: "관측 범위 안", tone: "ok" },
  low: { text: "관측 범위보다 적음", tone: "warn" },
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
              <span className="food-qty" role="cell" data-label="판매 수량">
                {count(item.today_quantity)}
              </span>
              <span className="food-range" role="cell" data-label="과거 관측 범위">
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
        <BasisToggle summary={`최근 같은 ${data.weekday}요일 ${first.weeks_used}번 기준`}>
          <p>
            과거 관측 범위는 같은 {data.weekday}요일, 같은 시각({hourLabel(data.cutoff_hour)})까지 집계한 최근 {first.weeks_used}번 중 가장 적었던 값~가장
            많았던 값이에요.
          </p>
          <p>통계적으로 &lsquo;정상&rsquo;이라는 뜻이 아니라 지난 기록이 움직인 폭이에요. 상품별이 아니라 대분류 기준이에요.</p>
        </BasisToggle>
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

// 점포를 등록하지 않았으면(처음 설정을 건너뛴 경우) 등록할 때까지 홈 위쪽에 안내를 남깁니다.
function SetupReminder() {
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    let alive = true;
    request("/api/settings/setup")
      .then((s) => alive && setMissing(!s.has_location))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  if (!missing) return null;
  return (
    <Card title="점포를 등록해 주세요">
      <p className="card-note">점포 위치를 등록하면 설정에서 근처 학교의 방학을 자동으로 가져올 수 있어요.</p>
      <Link to="/setup" className="button">
        점포 등록하기
      </Link>
    </Card>
  );
}

export default function Home() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [attention, setAttention] = useState(null); // { total, today } 확인할 사항 건수 (요약 띠에 씁니다)

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
    <section className="home-page">
      {data?.has_data && <TodayBand data={data} attention={attention} />}

      <SetupReminder />

      {/* 컴퓨터 화면: 왼쪽에 매출·확인할 사항, 오른쪽에 AI 제안·집중 관리·내일 예상. 휴대폰에서는 slot 번호 순서대로 한 줄로 쌓입니다. */}
      <div className="home-grid">
        <div className="home-col">
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
            <div className="slot slot-attention">
              <AnomalyCard weekday={data.weekday} onSummary={setAttention} />
            </div>
          )}
        </div>
        <div className="home-col">
          <div className="slot slot-ai">
            <SuggestCard />
          </div>
          {data?.has_data && (
            <>
              <div className="slot slot-focus">
                <FocusFood data={data} />
              </div>
              <div className="slot slot-forecast">
                <ForecastCard />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
