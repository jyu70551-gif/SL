import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "../api.js";
import { Card } from "../components/Card.jsx";
import { DiffLine } from "../components/Change.jsx";
import Disclosure from "../components/Disclosure.jsx";
import { AlertTriangle, ArrowLink } from "../components/Icons.jsx";
import SalesChart, { CHART_STYLE, ChartLegend } from "../components/SalesChart.jsx";
import { hourLabel, longDateLabel, periodWord, rangeText, won } from "../format.js";
import { centerMethod, interpret } from "../salesText.js";

const SHOWN_DAYS = 90; // "최근" 매출 흐름: 최근 90일까지만 그립니다

export default function SalesDetail() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [showRange, setShowRange] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setData(await request("/api/sales/detail"));
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (failed) {
    return (
      <section className="analysis">
        <Link to="/" className="back-link">
          ← 홈으로
        </Link>
        <Card title="분석을 불러오지 못했어요">
          <p className="card-note">서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.</p>
          <button type="button" className="button secondary" onClick={load}>
            다시 시도
          </button>
        </Card>
      </section>
    );
  }
  if (data === null) return <p className="empty-note">불러오는 중…</p>;
  if (!data.has_data) {
    return (
      <section className="analysis">
        <Link to="/" className="back-link">
          ← 홈으로
        </Link>
        <Card title="아직 올린 파일이 없어요">
          <p className="card-note">매출 파일을 올리면 분석을 보여 드려요.</p>
        </Card>
      </section>
    );
  }

  const { test, cutoff_hour: hour } = data;
  const ready = test.status === "ready";
  const todayTotal = data.today.total_amount;
  const diff = ready ? todayTotal - test.center : null;
  const note = interpret(test, diff);
  const hourText = hourLabel(hour);

  const points = data.points.slice(-SHOWN_DAYS).map((p) => ({ date: p.date, amount: p.amount, cutoff_hour: hour }));
  // 비교 기준선·평소 변동 범위는 '비교 범위 보기'를 켰을 때만 그립니다.
  const refLines =
    ready && showRange
      ? [
          { value: test.center, kind: "center" },
          { value: test.low, kind: "bound" },
          { value: test.high, kind: "bound" },
        ]
      : [];
  const legend = [
    { label: "실제 매출", kind: "line", style: CHART_STYLE.actual },
    { label: "비교 기준", kind: "line", style: CHART_STYLE.center },
    { label: "평소 변동 범위", kind: "line", style: CHART_STYLE.bound },
  ];

  return (
    <section className="analysis">
      <Link to="/" className="back-link">
        ← 홈으로
      </Link>

      {/* 상단: 카드 테두리 없이 배경 위에. 핵심 숫자 → 해석 순서 */}
      <header className="analysis-top">
        <h1 className="analysis-title">{periodWord(hour)} 매출 점검</h1>
        <p className="analysis-meta">
          {longDateLabel(data.date)} · {hourText}까지
        </p>

        <div className="analysis-total">{won(todayTotal)}</div>
        {ready && (
          <DiffLine
            diff={diff}
            pct={test.center ? Math.round((diff / test.center) * 1000) / 10 : null}
            basis="이전 기록의 비교 기준"
            directional
          />
        )}

        <div className={`analysis-note ${note.tone}`}>
          {note.tone === "check" && <AlertTriangle className="note-icon" size={20} />}
          <p>{note.text}</p>
        </div>
        {test.status === "not_enough" && (
          <p className="analysis-sub">
            비교 가능한 기록 {test.n}/{test.min_days}
          </p>
        )}
        {ready && test.few_data && <p className="analysis-sub">비교한 기록이 {test.n}번뿐이라 참고용이에요.</p>}
      </header>

      {/* 중단: 그래프. 얇은 연보라 판매선, 선택 날짜의 점과 금액만 강조 */}
      <Card title="최근 매출 흐름">
        <div className="chart-head">
          <p className="analysis-sub">{hourText}까지 집계 · 단위: 원</p>
          {ready && (
            <button type="button" className="text-button" aria-pressed={showRange} onClick={() => setShowRange(!showRange)}>
              {showRange ? "비교 범위 숨기기" : "비교 범위 보기"}
            </button>
          )}
        </div>
        <SalesChart points={points} selectedDate={data.date} refLines={refLines} />
        {showRange && <ChartLegend items={legend} />}
      </Card>

      {/* 하단: 비교 근거(2단계), 분석 상세(3단계) */}
      <Disclosure label="어떤 기록과 비교했나요?">
        <ul className="basis-items">
          <li>
            {test.n === 0
              ? "비교할 이전 기록이 아직 없어요."
              : ready
                ? `이전 ${test.n}일의 기록과 비교했어요. (${rangeText(data.used_dates)})`
                : `이전 ${test.n}일의 기록(${rangeText(data.used_dates)})이 있지만, 비교하기에는 아직 부족해요. 최소 ${test.min_days}일이 필요해요.`}
          </li>
          <li>이번 비교는 요일을 구분하지 않고, 같은 집계 시간({hourText}까지)의 과거 기록만 사용했어요.</li>
          {ready && (
            <li>
              비교 기준 금액({won(test.center)})은 {centerMethod(test)}이에요.
            </li>
          )}
        </ul>
        <p className="basis-title">알아 두세요</p>
        <ul className="basis-items">
          <li>분석하는 날짜 이후의 기록은 쓰지 않았어요.</li>
          {ready && test.few_data && <li>비교한 기록이 {test.n}번뿐이라 참고용이에요.</li>}
          <li>연휴나 행사처럼 특별했던 날도 평소 기록에 섞여 있어요.</li>
          <li>파일을 올리지 않은 날은 0원으로 채우지 않고, 그래프 선을 이어 그리지도 않아요.</li>
          {data.excluded_other_hour > 0 && <li>집계 시간이 달라서 뺀 날이 {data.excluded_other_hour}일 있어요.</li>}
          <li>홈의 &lsquo;같은 {data.weekday}요일 기준&rsquo;은 같은 요일 최근 4번의 평균이라 금액이 달라요.</li>
        </ul>
        {ready && <ArrowLink to="/sales/analysis">분석 상세 보기</ArrowLink>}
      </Disclosure>

      {/* 확인이 필요한 경우에만 다음 행동을 보여줍니다. 대표 행동 버튼은 하나. */}
      {note.tone === "check" && (
        <section className="next-step">
          <h2 className="next-title">확인해 볼까요?</h2>
          <p>대분류별로 어디서 변했는지 보면 무슨 일이 있었는지 짐작하기 쉬워요.</p>
          <Link className="button" to="/">
            확인할 사항 보기
          </Link>
        </section>
      )}
    </section>
  );
}
