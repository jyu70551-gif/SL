import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, request } from "../api.js";
import AnomalyCard from "../components/AnomalyCard.jsx";
import { Card, NeedMore } from "../components/Card.jsx";
import { DiffLine } from "../components/Change.jsx";
import ForecastCard from "../components/ForecastCard.jsx";
import { StreetScene } from "../components/StoreScene.jsx";
import SuggestCard from "../components/SuggestCard.jsx";
import StockSignals from "../components/StockSignals.jsx";
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

// 화면 폭이 컴퓨터용인지 알려 줍니다. 카드의 읽는 순서가 컴퓨터와 휴대폰에서 다르므로, CSS 로 순서를 바꾸지 않고
// 보이는 순서와 같은 순서로 카드를 그려서 키보드(Tab) 이동 순서도 눈에 보이는 순서와 같게 합니다.
function useWide() {
  const query = "(min-width: 1024px)";
  const [wide, setWide] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setWide(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return wide;
}

export default function Home() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [attention, setAttention] = useState(null); // { total, today } 확인할 사항 건수 (요약 띠에 씁니다)
  const wide = useWide();

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

  const notices = (
    <>
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
    </>
  );
  const ready = data?.has_data;
  const attentionCard = ready && <AnomalyCard weekday={data.weekday} onSummary={setAttention} />;
  const stockCard = ready && <StockSignals />;
  const forecastCard = ready && <ForecastCard />;

  return (
    <section className="home-page">
      {ready && <TodayBand data={data} attention={attention} />}

      <SetupReminder />

      {/* 컴퓨터: 위쪽 두 칸(왼쪽 확인할 사항 60%, 오른쪽 AI 점검 요약과 내일 예상 매출 40%) 아래에 식품 발주 점검이 전체 너비로 옵니다.
          휴대폰: 확인할 사항 → 식품 발주 점검 → AI 점검 요약 → 내일 예상 매출 순서로 한 줄씩 쌓입니다. */}
      {wide ? (
        <>
          <div className="ops-grid">
            <div className="ops-col">
              {notices}
              {attentionCard}
            </div>
            <div className="ops-col">
              <SuggestCard />
              {forecastCard}
            </div>
          </div>
          {stockCard}
        </>
      ) : (
        <div className="home-stack">
          {notices}
          {attentionCard}
          {stockCard}
          <SuggestCard />
          {forecastCard}
        </div>
      )}
    </section>
  );
}
