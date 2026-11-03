import { useCallback, useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";
import { approxRange, longDate, periodLabel, hourLabel, won } from "../format.js";

// 내일 예상 매출: 하나의 값이 아니라 "얼마와 얼마 사이"로, 너무 정밀해 보이지 않게 어림해서 보여 줍니다.
// 어림은 화면에만 적용하고, 계산된 원래 값은 "예측 근거"를 펼치면 그대로 보입니다.
export default function ForecastCard() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    setData(null);
    request("/api/forecast/tomorrow")
      .then(setData)
      .catch(() => setData({ status: "failed" }));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!data || data.status === "no_data") return null;

  // 자료가 모자란 것(기다리면 됨)과 불러오지 못한 것(다시 시도)을 다르게 안내합니다.
  if (data.status === "failed") {
    return (
      <Card title="내일 예상 매출" aside="참고용">
        <p className="card-note">예상을 불러오지 못했어요. 잠시 뒤 다시 확인해 주세요.</p>
        <button type="button" className="button secondary" onClick={load}>
          다시 불러오기
        </button>
      </Card>
    );
  }
  if (data.status === "not_enough" || !data.low || !data.high) {
    return (
      <Card title="내일 예상 매출" aside="참고용">
        <p className="card-note">
          매출 기록이 더 쌓이면 예상해 드려요.{data.days ? ` (지금 ${data.days}일 쌓였어요)` : ""}
        </p>
      </Card>
    );
  }

  const period = periodLabel(data.cutoff_hour);
  const test = data.backtest;
  return (
    <Card title={`내일 ${period} 예상 매출`} aside="참고용">
      <p className="card-note">
        {longDate(data.target_date)} · {hourLabel(data.cutoff_hour)}까지 매출 기준
      </p>
      <div className="forecast-range">{approxRange(data.low, data.high)}</div>
      <button type="button" className="text-button" aria-expanded={open} onClick={() => setOpen(!open)}>
        예측 근거 보기 {open ? "▴" : "›"}
      </button>
      {open && (
        <div className="basis-panel">
          <ul className="basis-list">
            <li>
              계산된 범위: <strong>{won(data.low)} ~ {won(data.high)}</strong> (중심 약 {won(data.center)})
            </li>
            <li>
              쓴 방법: {data.method_name}
              {data.days_used ? ` · 매출 기록 ${data.days_used}일을 사용` : ""}
            </li>
            {data.factors?.length > 0 && (
              <li>
                반영한 것: {data.factors.map((f) => `${f.name} (${f.effect_pct > 0 ? "+" : "−"}${Math.abs(f.effect_pct)}%)`).join(", ")}
              </li>
            )}
            {test?.tests ? (
              <li>
                최근 {test.tests}일을 하루씩 맞혀 본 평균 오차는 약 {data.method === "model" ? test.model_error_pct : test.baseline_error_pct}%였어요. 범위는 그 오차를
                바탕으로 만들었어요.
              </li>
            ) : null}
            {data.notes?.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <p>
            범위는 지난 기록의 오차로 짐작한 것이라 실제 매출이 범위 밖일 수 있어요. 요일, 날씨, 방학 같은 조건으로 계산한 참고용 추정이고, 행사나 갑작스러운 일은
            반영하지 못해요.
          </p>
        </div>
      )}
    </Card>
  );
}
