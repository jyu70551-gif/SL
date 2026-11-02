import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "./Card.jsx";
import { dateLabel, hourLabel, won } from "../format.js";

// 내일 예상 매출: 하나의 값이 아니라 "얼마와 얼마 사이"로 보여 줍니다. (계산 방법과 근거는 문서에 있고 화면에는 싣지 않습니다)
export default function ForecastCard() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    request("/api/forecast/tomorrow")
      .then((d) => alive && setData(d))
      .catch(() => alive && setData({ status: "failed" }));
    return () => {
      alive = false;
    };
  }, []);

  if (!data || data.status === "no_data") return null;

  let body;
  if (data.status === "failed") {
    body = <p className="card-note">예상을 불러오지 못했어요. 잠시 뒤 다시 확인해 주세요.</p>;
  } else if (data.status === "not_enough" || !data.low || !data.high) {
    body = <p className="card-note">데이터가 더 쌓이면 예상해 드려요.</p>;
  } else {
    body = (
      <>
        <p className="card-note">
          {dateLabel(data.target_date)} · {hourLabel(data.cutoff_hour)}까지 매출 기준
        </p>
        <div className="headline">
          <div className="headline-value">
            {won(data.low)} ~ {won(data.high)}
          </div>
          <p className="diff-line same">사이일 거예요</p>
        </div>
      </>
    );
  }
  return (
    <Card title="내일 예상 매출" aside="참고용">
      {body}
    </Card>
  );
}
