import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "../api.js";
import { Card } from "../components/Card.jsx";
import { DiffLine } from "../components/Change.jsx";
import { shortDate, won } from "../format.js";
import { categoryLabel, STORE } from "../reasons.js";

const SHOWN = 6; // 처음에 보여 줄 기록 수. 나머지는 펼쳐서 봅니다.

export default function Reviewed() {
  const [items, setItems] = useState(null);
  const [failed, setFailed] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [busyKey, setBusyKey] = useState(null);
  const [asking, setAsking] = useState(null); // 취소할지 되묻는 중인 항목
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setItems((await request("/api/anomalies/reviewed")).items);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function cancel(item) {
    const key = `${item.category}|${item.date}`;
    setBusyKey(key);
    setAsking(null);
    setSaveError(false);
    try {
      await request("/api/anomalies/unreview", { method: "POST", body: { category: item.category, date: item.date } });
      await load();
    } catch {
      // 저장되지 않았으면 항목은 이 목록에 그대로 남깁니다.
      setSaveError(true);
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <section>
      <Link to="/" className="back-link">
        ← 홈으로
      </Link>
      <div className="page-head">
        <h1 className="page-title">운영 상황 기록</h1>
        <p className="page-meta">점주님이 직접 입력한 기록이에요. 기록을 취소하면 다시 확인할 사항에 올라와요.</p>
      </div>

      {failed && (
        <Card title="목록을 불러오지 못했어요">
          <p className="card-note">서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.</p>
        </Card>
      )}
      {!failed && items === null && <p className="empty-note">불러오는 중…</p>}

      {items && (
        <Card title="기록한 항목" aside={`${items.length}건`}>
          {items.length === 0 ? (
            <p className="card-note">기록한 항목이 없어요.</p>
          ) : (
            <ul className="day-list">
              {(showAll ? items : items.slice(0, SHOWN)).map((item) => (
                <li key={`${item.category}|${item.date}`} className="day-row">
                  {item.category === STORE ? (
                    <div className="record-link">
                    <span className="day-top">
                      <span className="day-date">
                        <strong>{categoryLabel(item.category)}</strong> · {shortDate(item.date)}
                      </span>
                      {item.amount != null && <span className="day-amount">{won(item.amount)}</span>}
                    </span>
                    {item.baseline != null && (
                      <DiffLine diff={item.amount - item.baseline} pct={item.change_pct} basis="비교 기준" />
                    )}
                    </div>
                  ) : (
                    <Link
                      className="record-link"
                      to={`/category/${encodeURIComponent(item.category)}?date=${item.date}`}
                    >
                    <span className="day-top">
                      <span className="day-date">
                        <strong>{categoryLabel(item.category)}</strong> · {shortDate(item.date)}
                      </span>
                      {item.amount != null && <span className="day-amount">{won(item.amount)}</span>}
                    </span>
                    {item.baseline != null && (
                      <DiffLine diff={item.amount - item.baseline} pct={item.change_pct} basis="비교 기준" />
                    )}
                    </Link>
                  )}
                  {item.reason_labels?.length > 0 && (
                    <p className="record-reasons">
                      점주 기록: {item.reason_labels.join(", ")}
                      {item.time_hint && ` · ${item.time_hint}`}
                      {item.source === "ai" && " · AI가 정리, 점주가 확인"}
                    </p>
                  )}
                  {item.source === "ai" && item.raw_text && <p className="record-memo">&ldquo;{item.raw_text}&rdquo;</p>}
                  {item.memo && <p className="record-memo">&ldquo;{item.memo}&rdquo;</p>}
                  <div className="day-action">
                    {asking === `${item.category}|${item.date}` ? (
                      <span className="ask-row" role="group" aria-label="기록 취소 확인">
                        <span className="muted">이 기록을 취소할까요? 다시 확인할 사항에 올라와요.</span>
                        <button type="button" className="text-button" disabled={busyKey === `${item.category}|${item.date}`} onClick={() => cancel(item)}>
                          취소하기
                        </button>
                        <button type="button" className="text-button" onClick={() => setAsking(null)}>
                          아니요
                        </button>
                      </span>
                    ) : (
                      <button type="button" className="text-button" onClick={() => setAsking(`${item.category}|${item.date}`)}>
                        기록 취소
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {items.length > SHOWN && (
            <button type="button" className="text-button more-toggle" aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
              {showAll ? "접기" : `나머지 ${items.length - SHOWN}건 더 보기`}
            </button>
          )}
          {saveError && (
            <p className="error" role="alert">
              취소하지 못했어요. 항목은 그대로 남겨 두었어요.
            </p>
          )}
        </Card>
      )}
    </section>
  );
}
