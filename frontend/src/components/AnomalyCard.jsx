import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "../api.js";
import { won, shortDate } from "../format.js";
import { Card, NeedMore } from "./Card.jsx";
import { DiffLine } from "./Change.jsx";
import { ArrowLink } from "./Icons.jsx";

// 한 줄 전체가 링크입니다. 순서: 분류명 · 발생 날짜 → 판매액 → 비교 금액 차이(증가율은 작게)
function Row({ entry }) {
  return (
    <li>
      <Link
        className="attention-row"
        to={`/category/${encodeURIComponent(entry.category)}?date=${entry.date}`}
      >
        <div className="row-main">
          <span className="row-title">
            <span className="row-flag" aria-hidden="true">
              ⚠
            </span>
            <strong>{entry.category}</strong>
            <span className="row-date"> · {shortDate(entry.date)}</span>
          </span>
          <span className="row-chevron" aria-hidden="true">
            ›
          </span>
        </div>
        <div className="row-amount">{won(entry.amount)}</div>
        <DiffLine diff={entry.amount - entry.baseline} pct={entry.change_pct} basis="비교 기준" />
      </Link>
    </li>
  );
}

function Group({ heading, entries }) {
  return (
    <div className="attention-group">
      {heading && <h3 className="group-title">{heading}</h3>}
      <ul className="attention-list">
        {entries.map((entry) => (
          <Row key={`${entry.category}|${entry.date}`} entry={entry} />
        ))}
      </ul>
    </div>
  );
}

export default function AnomalyCard({ weekday }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setData(await request("/api/anomalies"));
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const title = "확인할 사항";
  if (failed) {
    return (
      <Card title={title}>
        <p className="card-note">목록을 불러오지 못했어요.</p>
        <button type="button" className="text-button" onClick={load}>
          다시 시도
        </button>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card title={title}>
        <p className="card-note">불러오는 중…</p>
      </Card>
    );
  }

  if (data.status === "not_enough") {
    return (
      <Card title={title}>
        <p className="card-note">판단 자료 부족</p>
        <NeedMore comparison={data} weekday={weekday} />
      </Card>
    );
  }

  // 대분류 단위 목록을 (분류, 날짜) 한 건씩으로 풀고, 오늘의 변화와 이전 미확인 건을 나눕니다.
  const entries = data.items
    .flatMap((item) => item.flagged.map((f) => ({ category: item.category, ...f })))
    .sort((a, b) => (a.date === b.date ? a.category.localeCompare(b.category, "ko") : b.date.localeCompare(a.date)));
  const todays = entries.filter((e) => e.date === data.date);
  const earlier = entries.filter((e) => e.date !== data.date);

  let body;
  let cardTitle = title;
  let aside = null;
  if (entries.length === 0) {
    body = <p className="all-clear">✓ 지금 확인할 사항이 없어요.</p>;
  } else if (todays.length && earlier.length) {
    aside = `${entries.length}건`;
    body = (
      <>
        <Group heading={`오늘의 변화 · ${todays.length}건`} entries={todays} />
        <Group heading={`이전 미확인 사항 · ${earlier.length}건`} entries={earlier} />
      </>
    );
  } else if (todays.length) {
    cardTitle = `오늘의 변화 · ${todays.length}건`;
    body = <Group entries={todays} />;
  } else {
    cardTitle = `이전 미확인 사항 · ${earlier.length}건`;
    body = <Group entries={earlier} />;
  }

  return (
    <Card title={cardTitle} aside={aside} keyMark={entries.length > 0}>
      {body}
      <ArrowLink to="/reviewed">운영 상황 기록 보기</ArrowLink>
    </Card>
  );
}
