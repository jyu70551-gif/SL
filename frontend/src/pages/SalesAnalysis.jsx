import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "../api.js";
import { Card, NeedMore } from "../components/Card.jsx";
import { hourLabel, longDateLabel, rangeText, won } from "../format.js";
import { centerMethod, detectionLabel } from "../salesText.js";

function percentText(pct) {
  if (pct < 0.1) return "0.1% 미만";
  return `${pct.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`;
}

function pValueText(p) {
  return p < 0.001 ? "0.001보다 작음" : p.toLocaleString("ko-KR", { maximumFractionDigits: 3 });
}

// 3단계: 분석 상세. 통계 방법, 예측 범위, 검정 결과, 가정과 검증 정보.
export default function SalesAnalysis() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

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

  const back = (
    <Link to="/sales" className="back-link">
      ← 매출 점검으로
    </Link>
  );

  if (failed) {
    return (
      <section className="analysis">
        {back}
        <Card title="분석을 불러오지 못했어요">
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
        {back}
        <Card title="아직 올린 파일이 없어요">
          <p className="card-note">매출 파일을 올리면 분석을 보여 드려요.</p>
        </Card>
      </section>
    );
  }

  const { test, cutoff_hour: hour } = data;
  const ready = test.status === "ready";
  const today = data.today.total_amount;
  const hourText = hourLabel(hour);

  return (
    <section className="analysis">
      {back}
      <header className="analysis-top">
        <h1 className="analysis-title">분석 상세</h1>
        <p className="analysis-meta">
          {longDateLabel(data.date)} · {hourText}까지
        </p>
      </header>

      <Card title="이번 결과">
        <dl className="stat-list">
          <div>
            <dt>오늘 총매출</dt>
            <dd>{won(today)}</dd>
          </div>
          {ready && (
            <div>
              <dt>비교 기준 금액</dt>
              <dd>{won(test.center)}</dd>
            </div>
          )}
          <div>
            <dt>탐지 결과</dt>
            <dd>{detectionLabel(test)}</dd>
          </div>
          <div>
            <dt>비교한 기록</dt>
            <dd>
              {test.n}일{test.n > 0 && ` (${rangeText(data.used_dates)})`}
            </dd>
          </div>
        </dl>
        {ready && <p className="card-note">비교 기준 금액은 {centerMethod(test)}이에요.</p>}
        {test.status === "not_enough" && (
          <NeedMore
            comparison={{
              weeks_used: test.n,
              min_days: test.min_days,
              needed_more: test.needed_more,
              excluded_other_hour: data.excluded_other_hour,
            }}
            scopeText={`${hourText}까지 집계한 날의 기록이`}
          />
        )}
        {test.status === "no_variation" && (
          <p className="card-note">비교한 기록의 매출이 모두 같아서, 오늘이 평소에서 얼마나 벗어났는지 계산할 수 없어요.</p>
        )}
      </Card>

      {ready && (
        <>
          <Card title="평소 변동 범위">
            <dl className="stat-list">
              <div>
                <dt>예측 범위 (95%)</dt>
                <dd>
                  {won(test.low)} ~ {won(test.high)}
                </dd>
              </div>
              <div>
                <dt>오늘의 위치</dt>
                <dd>
                  {test.side === "high" ? "높은 쪽" : "낮은 쪽"} {test.side === "high" ? "상위" : "하위"} {percentText(test.tail_pct)}
                </dd>
              </div>
              <div>
                <dt>오늘보다 낮았던 기록</dt>
                <dd>
                  {test.n}일 중 {test.rank_below}일
                </dd>
              </div>
            </dl>
            <p className="card-note">
              이 범위는 &lsquo;평균이 어디쯤인지&rsquo;(신뢰구간)가 아니라, 이전 기록의 분포로 볼 때 <strong>하루 매출 하나가 들어올 것으로
              예상되는 범위</strong>(예측구간)예요. 오늘 값이 이 범위 밖이면 탐지 기준을 넘었다고 봐요.
            </p>
          </Card>

          <Card title="검정 결과">
            <dl className="stat-list">
              <div>
                <dt>t 값</dt>
                <dd>{test.t}</dd>
              </div>
              <div>
                <dt>자유도</dt>
                <dd>{test.df}</dd>
              </div>
              <div>
                <dt>p값 (양쪽)</dt>
                <dd>{pValueText(test.p_value)}</dd>
              </div>
              <div>
                <dt>탐지 기준</dt>
                <dd>p값 0.05 미만</dd>
              </div>
            </dl>
            <p className="card-note">
              p값은 &lsquo;이전 기록의 분포가 맞다고 가정할 때, 오늘만큼 평소에서 벗어난 값이 나올 확률&rsquo;이에요. 0.05보다 작으면 평소 변동만으로
              설명하기 어렵다고 보고 탐지 기준 초과로 표시해요. <strong>이번 변화가 우연일 확률이나 원인을 뜻하지는 않아요.</strong>
            </p>
          </Card>
        </>
      )}

      <Card title="통계 방법과 가정">
        <ul className="basis-items">
          <li>
            이전 기록 {test.n}일을 {test.scale === "log" ? "비율(%) 기준(로그)으로 바꿔" : "금액 그대로"} 평균과 표준편차를 구했어요.
            {test.scale === "log" ? " 매출은 몇 %씩 늘고 줄며 흔들리기 때문이고, 이렇게 하면 평소 범위가 0원 아래로 내려가지 않아요." : " 0원인 날이 있어 로그를 쓸 수 없었어요."}
          </li>
          <li>
            오늘 값이 그 분포에서 벗어난 정도를 t 분포로 계산했어요(예측구간 검정, 양쪽, 유의수준 5%). 기록이 적으면 범위를 넓게 잡아
            신중하게 판정하고, 쌓이면 범위가 좁아져요.
          </li>
          <li>비교 기록은 분석 날짜 이전, 같은 집계 시간({hourText}까지)의 모든 날이고 요일은 구분하지 않아요.</li>
        </ul>
        <p className="basis-title">이 결과가 기대는 가정</p>
        <ul className="basis-items">
          <li>날짜별 매출이 서로 독립이라고 가정해요. 계절, 추세, 연휴의 영향은 반영하지 않아요.</li>
          <li>비율 기준 매출이 종 모양(정규)분포에 가깝다고 가정해요. 기록이 적으면 이 가정을 확인하기 어려워요.</li>
          <li>이전 기록이 &lsquo;평소&rsquo;를 대표한다고 가정해요. 가게 상황이 크게 바뀌었다면 맞지 않을 수 있어요.</li>
          <li>요일마다 매출 수준이 다르면 그 차이도 평소의 흔들림에 섞여 범위가 넓어져요.</li>
        </ul>
        <p className="basis-title">검증 정보</p>
        <ul className="basis-items">
          <li>
            비교한 기록 {test.n}일 · 판단에 필요한 최소 기록 {test.min_days}일 · 참고용으로 보는 기준 5일 미만
          </li>
          <li>t 분포 계산은 표준 t표의 값과 대조해 확인했어요.</li>
          <li>탐지 결과는 통계적 판단이고, 매장 운영이 정상인지 아닌지를 뜻하지 않아요.</li>
        </ul>
      </Card>
    </section>
  );
}
