import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { request } from "../api.js";
import { isToday, won, shortDate } from "../format.js";
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
            {/* 경고 표시는 며칠째 안 팔리는 등 이어지는 변화가 탐지된 항목에만 붙입니다. 단순한 증가·감소는 ▲▼와 문구만 씁니다. */}
            {entry.kind_text && (
              <span className="row-flag" aria-hidden="true">
                ⚠
              </span>
            )}
            <strong>{entry.category}</strong>
            <span className="row-date"> · {shortDate(entry.date)}</span>
          </span>
          <span className="row-chevron" aria-hidden="true">
            ›
          </span>
        </div>
        <div className="row-amount">{won(entry.amount)}</div>
        <DiffLine diff={entry.amount - entry.baseline} pct={entry.change_pct} basis="비교 기준" />
        {entry.kind_text && <p className="diff-line">{entry.kind_text}</p>}
        {entry.calendar_text && <p className="diff-line calendar-note">{entry.calendar_text}</p>}
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

const SHOWN = 3; // 처음에는 이만큼만 보여 주고 나머지는 펼쳐서 봅니다

// 대분류 단위 목록을 (분류, 날짜) 한 건씩으로 풀고 최신 날짜 순으로 놓습니다.
function entriesOf(data) {
  return data.items
    .flatMap((item) => item.flagged.map((f) => ({ category: item.category, ...f })))
    .sort((a, b) => (a.date === b.date ? a.category.localeCompare(b.category, "ko") : b.date.localeCompare(a.date)));
}

// onSummary: 홈 맨 위 요약 띠가 "확인할 사항 N건"을 말할 수 있게 건수를 알려 줍니다.
export default function AnomalyCard({ weekday, onSummary }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!data || data.status === "not_enough") return;
    const entries = entriesOf(data);
    onSummary?.({ total: entries.length, today: entries.filter((e) => e.date === data.date).length });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

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

  // 오늘의 변화와 이전 미확인 건을 나눕니다. 길면 앞의 몇 건만 보여 주고 펼칠 수 있게 합니다.
  const entries = entriesOf(data);
  const todays = entries.filter((e) => e.date === data.date);
  const earlier = entries.filter((e) => e.date !== data.date);
  // 오늘(기준일)의 변화는 항상 다 보여 주고, 이전 미확인 사항이 많으면 앞의 몇 건만 보여 준 뒤 접어 둡니다.
  const room = Math.max(0, SHOWN - todays.length);
  const hidden = open ? 0 : Math.max(0, earlier.length - room);
  const showToday = todays;
  const showEarlier = open ? earlier : earlier.slice(0, room);
  const dayName = isToday(data.date) ? "오늘" : "기준일";

  let body;
  let cardTitle = title;
  let aside = null;
  if (entries.length === 0) {
    body = <p className="all-clear">✓ 지금 확인할 사항이 없어요.</p>;
  } else if (todays.length && earlier.length) {
    aside = `${entries.length}건`;
    body = (
      <>
        <Group heading={`${dayName}의 변화 · ${todays.length}건`} entries={showToday} />
        {showEarlier.length > 0 && <Group heading={`이전 미확인 사항 · ${earlier.length}건`} entries={showEarlier} />}
      </>
    );
  } else if (todays.length) {
    cardTitle = `${dayName}의 변화 · ${todays.length}건`;
    body = <Group entries={showToday} />;
  } else {
    cardTitle = `이전 미확인 사항 · ${earlier.length}건`;
    body = <Group entries={showEarlier} />;
  }

  return (
    <div id="attention">
      <Card title={cardTitle} aside={aside} keyMark={entries.length > 0}>
        {body}
        {earlier.length > room && (
          <button type="button" className="text-button more-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "이전 미확인 접기" : `이전 미확인 ${hidden}건 더 보기`}
          </button>
        )}
        <ArrowLink to="/reviewed">운영 상황 기록 보기</ArrowLink>
      </Card>
    </div>
  );
}
