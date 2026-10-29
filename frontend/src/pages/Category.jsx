import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { request } from "../api.js";
import { BasisToggle, Card, NeedMore } from "../components/Card.jsx";
import { DiffLine } from "../components/Change.jsx";
import SalesChart, { ChartLegend } from "../components/SalesChart.jsx";
import { hourLabel, monthDay, shortDate, won } from "../format.js";

// 점주가 고르는 당시 특이사항. 점주가 직접 입력한 기록이며 통계로 입증된 원인이 아닙니다.
const REASONS = [
  ["promo", "행사·진열 변경"],
  ["bulk", "단체 구매"],
  ["stock", "입고·품절 관련 사항"],
  ["data_check", "데이터 확인 필요"],
  ["other", "기타"],
  ["unknown", "모르겠어요"],
];

// 주소에 날짜가 없으면: 아직 기록하지 않은 가장 최근의 큰 변화 → 가장 최근의 큰 변화 → 가장 최근 날
function pickDefault(points) {
  const big = points.filter((p) => p.anomaly).reverse();
  return big.find((p) => !p.anomaly.reviewed) ?? big[0] ?? points[points.length - 1];
}

function RecordForm({ category, point, onChanged }) {
  const saved = point.record;
  const [reasons, setReasons] = useState(saved?.reasons ?? []);
  const [memo, setMemo] = useState(saved?.memo ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  // 날짜를 옮기면 그 날짜에 저장된 내용으로 다시 채웁니다.
  useEffect(() => {
    setReasons(saved?.reasons ?? []);
    setMemo(saved?.memo ?? "");
    setError(false);
  }, [point.date, saved]);

  function toggle(key) {
    setReasons((current) => {
      if (key === "unknown") return current.includes("unknown") ? [] : ["unknown"]; // "모르겠어요"는 다른 선택과 함께 둘 수 없음
      const rest = current.filter((k) => k !== "unknown");
      return rest.includes(key) ? rest.filter((k) => k !== key) : [...rest, key];
    });
  }

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(false);
    try {
      await request("/api/anomalies/review", {
        method: "POST",
        body: { category, dates: [point.date], reasons, memo },
      });
      await onChanged();
    } catch {
      setError(true); // 저장되지 않았으면 화면도 그대로 둡니다.
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setError(false);
    try {
      await request("/api/anomalies/unreview", { method: "POST", body: { category, date: point.date } });
      await onChanged();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="운영 상황 기록" aside={saved ? "✓ 기록됨" : null}>
      <form onSubmit={submit} className="record-form">
        <fieldset className="record-fieldset">
          <legend className="record-legend">당시 특이사항이 있었나요?</legend>
          {REASONS.map(([key, label]) => (
            <label key={key} className="check-row">
              <input type="checkbox" checked={reasons.includes(key)} onChange={() => toggle(key)} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <label className="memo-label" htmlFor="record-memo">
          메모 (선택)
        </label>
        <textarea
          id="record-memo"
          className="memo-input"
          rows={3}
          maxLength={300}
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          placeholder="예: 단체 주문이 들어왔어요"
        />
        <p className="card-note">점주님이 직접 입력하는 기록이에요. 통계로 확인된 원인은 아니에요.</p>
        <div className="button-row">
          <button type="submit" className="button" disabled={busy || reasons.length === 0}>
            {saved ? "기록 수정" : "운영 상황 기록"}
          </button>
          {saved && (
            <button type="button" className="button secondary" disabled={busy} onClick={cancel}>
              기록 취소
            </button>
          )}
        </div>
        {error && (
          <p className="error" role="alert">
            저장하지 못했어요. 잠시 후 다시 눌러 주세요.
          </p>
        )}
      </form>
    </Card>
  );
}

export default function Category() {
  const { name } = useParams();
  const [params] = useSearchParams();
  const wantedDate = params.get("date");
  const [series, setSeries] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setSeries(await request(`/api/anomalies/series?category=${encodeURIComponent(name)}`));
    } catch {
      setFailed(true);
    }
  }, [name]);

  useEffect(() => {
    load();
  }, [load]);

  const points = series?.points ?? [];
  const latest = points[points.length - 1];
  const point = series && latest ? (points.find((p) => p.date === wantedDate) ?? pickDefault(points)) : null;
  const anomaly = point?.anomaly;
  const ready = point?.typical != null;
  const baseline = anomaly ? anomaly.baseline : point?.typical;
  const title = !point
    ? name
    : anomaly
      ? `${name} 판매 ${anomaly.direction === "high" ? "증가" : "감소"}`
      : `${name} 판매 현황`;
  const dates = point?.baseline_dates ?? [];

  return (
    <section>
      <Link to="/" className="back-link">
        ← 홈으로
      </Link>

      {failed && (
        <Card title="그래프를 불러오지 못했어요">
          <p className="card-note">이 대분류를 찾을 수 없거나 서버에 연결할 수 없어요.</p>
        </Card>
      )}
      {!failed && !series && <p className="empty-note">불러오는 중…</p>}

      {point && (
        <>
          {/* 1) 핵심 결과 */}
          <div className="page-head">
            <h1 className="page-title">{title}</h1>
            <p className="page-meta">
              {shortDate(point.date)} · {hourLabel(point.cutoff_hour)}까지
            </p>
            {point.date !== latest.date && (
              <p className="page-meta">조회 기준일 {shortDate(latest.date)}</p>
            )}
          </div>

          <div className="headline detail-headline">
            <div className="headline-value">{won(point.amount)}</div>
            {ready ? (
              <>
                {anomaly && anomaly.baseline === 0 ? (
                  <p className="diff-line">평소에는 거의 팔리지 않던 분류인데 이날은 팔렸어요.</p>
                ) : (
                  <DiffLine
                    diff={point.amount - baseline}
                    pct={anomaly ? anomaly.change_pct : baseline ? Math.round(((point.amount - baseline) / baseline) * 1000) / 10 : null}
                    basis={`같은 요일 비교 기준 ${won(baseline)}`}
                  />
                )}
                <BasisToggle
                  summary={
                    point.sparse
                      ? `같은 요일 ${point.weeks_used}번 중 팔린 날의 중간값`
                      : `같은 요일 ${point.weeks_used}번의 중간값`
                  }
                >
                  <p>
                    {shortDate(point.date)} <strong>이전</strong>, 같은 요일이면서 같은 시각({hourLabel(point.cutoff_hour)})까지 집계한{" "}
                    {point.weeks_used}번({dates.map(monthDay).join(", ")})의 <strong>중간값</strong>이에요. 한 번 크게 튄 날에 덜
                    흔들리도록 평균 대신 중간값을 써요.
                  </p>
                  {point.sparse && <p>평소 대부분 0원인 분류라서, 팔린 날끼리의 중간값으로 비교했어요.</p>}
                  <p>홈의 &lsquo;매출 요약&rsquo;은 총매출을 최근 4번의 평균으로 비교하므로 기준이 달라요.</p>
                </BasisToggle>
              </>
            ) : (
              <>
                <p className="diff-line">판단 자료 부족</p>
                <NeedMore
                  comparison={{
                    weeks_used: point.weeks_used,
                    min_days: series.min_days,
                    needed_more: Math.max(0, series.min_days - point.weeks_used),
                  }}
                  weekday="같은"
                />
              </>
            )}
          </div>

          {/* 2) 그래프 */}
          <Card title="날짜별 판매액">
            <SalesChart points={points} selectedDate={point.date} />
            <ChartLegend />
            <p className="card-note">
              파일을 올린 날짜만 그려요. 선이 끊긴 구간은 올리지 않은 날(미수집)이고, 0원이 아니에요.
            </p>
          </Card>

          {/* 3) 운영 상황 기록: 판매 변화가 큰 날이거나 이미 기록한 날짜에만 */}
          {(anomaly || point.record) && <RecordForm category={name} point={point} onChanged={load} />}
        </>
      )}
    </section>
  );
}
