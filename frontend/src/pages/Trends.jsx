import { useCallback, useEffect, useState } from "react";
import { request } from "../api.js";
import { monthDay } from "../format.js";

const count = (n) => n.toLocaleString("ko-KR"); // 건수 앞에 '개'가 붙지 않게 숫자만 씁니다

// '요즘 뜨는 식품' 탭 (docs/trends.md). 게시물 수·증가율·순위는 모두 서버가 코드로 계산한 값이고, 여기서는 보여 주기만 합니다.
// AI 는 설명 문장만 씁니다. 수집 못 한 날은 0건이 아니라 '모름'으로 보여 줍니다.
const MODE = {
  demo: { text: "시연 데이터", note: "지어낸 가짜 게시물이에요. 실제 SNS 언급량이 아니에요.", tone: "demo" },
  real: { text: "실제 수집 데이터", note: "", tone: "real" },
  mixed: { text: "실제·시연 데이터 섞임", note: "시연 데이터가 섞여 있어요. 실제 SNS 언급량으로 보면 안 돼요.", tone: "demo" },
  none: { text: "수집된 데이터 없음", note: "아직 수집된 게시물이 없어요. 실제 수집 공급원은 연결되기 전이에요.", tone: "none" },
};
const AI_NOTE = { unavailable: "AI를 지금 쓸 수 없어요.", timeout: "AI 응답이 늦어서 설명을 만들지 못했어요.", guard: "AI 설명이 검사를 통과하지 못했어요." };

function rangeText(range) {
  return `${monthDay(range[0])} ~ ${monthDay(range[1])}`;
}

function Spark({ daily }) {
  // 못 가져온 날(posts=null)은 선을 끊어서 0건처럼 보이지 않게 합니다. 가운데 세로선이 이전/최근 기간의 경계입니다.
  const max = Math.max(1, ...daily.map((d) => d.posts ?? 0));
  const w = 140;
  const h = 36;
  const x = (i) => (i / (daily.length - 1)) * w;
  const y = (v) => h - 3 - (v / max) * (h - 8);
  const runs = [];
  let run = [];
  daily.forEach((d, i) => {
    if (d.posts == null) {
      if (run.length) runs.push(run);
      run = [];
    } else {
      run.push(`${x(i).toFixed(1)},${y(d.posts).toFixed(1)}`);
    }
  });
  if (run.length) runs.push(run);
  const half = x(daily.length / 2 - 0.5);
  const gaps = daily.filter((d) => d.posts == null).length;
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`일별 게시물 추이${gaps ? `, 수집하지 못한 날 ${gaps}일` : ""}`}>
      <line x1={half} x2={half} y1="2" y2={h - 2} className="spark-split" />
      {runs.map((r, i) => (r.length > 1 ? <polyline key={i} points={r.join(" ")} className="spark-line" /> : <circle key={i} cx={r[0].split(",")[0]} cy={r[0].split(",")[1]} r="2" className="spark-dot" />))}
    </svg>
  );
}

function Change({ item }) {
  const ch = item.change;
  if (!ch) return <span className="trend-change none">비교할 수 없어요</span>;
  if (ch.new) return <span className="trend-change up">새롭게 관측됨 · +{count(ch.delta)}건</span>;
  const sign = ch.delta > 0 ? "+" : ch.delta < 0 ? "−" : "";
  const tone = ch.delta > 0 ? "up" : ch.delta < 0 ? "down" : "none";
  return (
    <span className={`trend-change ${tone}`}>
      {ch.delta > 0 ? "▲" : ch.delta < 0 ? "▼" : ""} {sign}
      {count(Math.abs(ch.delta))}건 · {sign}
      {Math.abs(ch.rate_pct)}%
    </span>
  );
}

function Explanation({ foodId, state, onChange }) {
  const [busy, setBusy] = useState(false);
  async function make(refresh) {
    setBusy(true);
    try {
      onChange(await request(`/api/trends/foods/${foodId}/explanation`, { method: "POST", body: { refresh } }));
    } catch {
      onChange({ status: "failed", error: "network" });
    } finally {
      setBusy(false);
    }
  }
  if (!state) return <p className="card-note">설명을 불러오는 중…</p>;
  if (busy) return <p className="card-note" role="status">설명을 만들고 있어요…</p>;
  if (state.status === "ok") {
    return (
      <>
        <p className="trend-summary">{state.explanation.summary}</p>
        {state.stale && <p className="card-note">근거가 새로 쌓였어요. 설명이 오래됐을 수 있어요.</p>}
      </>
    );
  }
  if (state.status === "insufficient") return <p className="card-note">{state.message}.</p>;
  if (state.status === "failed" || state.status === "unavailable") {
    return (
      <>
        <p className="card-note">설명을 만들지 못했어요. {AI_NOTE[state.error] ?? AI_NOTE[state.state] ?? ""} 집계와 근거 콘텐츠는 그대로 볼 수 있어요.</p>
        <button type="button" className="button secondary" onClick={() => make(false)}>
          다시 시도
        </button>
      </>
    );
  }
  return (
    <button type="button" className="button secondary" onClick={() => make(false)}>
      AI 설명 만들기
    </button>
  );
}

function Detail({ item, explanation, evidence, onExplain }) {
  const ex = explanation?.status === "ok" ? explanation.explanation : null;
  // 근거 번호는 아래 근거 콘텐츠 목록의 순서입니다. 목록이 아직 오기 전에는 번호 대신 기다리라고 보여 줍니다.
  const label = (ids) => ids.map((id) => (evidence ? `근거 ${evidence.findIndex((e) => e.id === id) + 1}` : "근거 불러오는 중")).join(", ");
  const sections = [
    ["confirmed", "확인된 계기", "공식 발표 등 출처에서 확인한 사실"],
    ["recurring", "자주 등장하는 내용", "수집한 게시물에서 반복해 언급된 주제 (게시물의 주장이고 사실로 확인된 것은 아니에요)"],
    ["interpretation", "해석", "관심 증가와 관련됐을 가능성이 있는 설명이에요. 원인으로 단정하지 않아요"],
  ];
  return (
    <div className="basis-panel trend-detail">
      {ex && (
        <div className="trend-explain">
          {sections.map(([key, title, note]) => (
            <div key={key}>
              <h4 className="group-title">{title}</h4>
              <p className="muted">{note}</p>
              {ex[key].length === 0 ? <p className="muted">{key === "confirmed" ? "공식 발표로 확인된 계기는 없어요." : "해당 내용이 없어요."}</p> : (
                <ul className="basis-list">
                  {ex[key].map((entry) => (
                    <li key={entry.text}>
                      {entry.text} <span className="muted">({label(entry.content_ids)})</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          <p className="muted">AI가 근거 콘텐츠를 풀어 쓴 설명이에요. 만든 때 {explanation.created_at.slice(0, 16).replace("T", " ")} · 숫자는 서버가 센 값이에요.</p>
          <button type="button" className="text-button" onClick={() => onExplain(true)}>
            설명 다시 만들기
          </button>
        </div>
      )}
      <h4 className="group-title">근거 콘텐츠</h4>
      {evidence === null && <p className="muted">불러오는 중…</p>}
      {evidence?.length === 0 && <p className="muted">이 기간에 근거로 보여 줄 콘텐츠가 없어요.</p>}
      <ol className="trend-evidence">
        {(evidence ?? []).map((e) => (
          <li key={e.id}>
            <span className={`trend-kind ${e.kind}`}>{e.kind === "official" ? "공식 발표" : "게시물"}</span>
            {e.is_ad && <span className="trend-kind ad">광고·협찬 표시</span>}
            <span className="muted"> {monthDay(e.posted_on)}</span>
            <p>{e.text}</p>
            {e.url ? (
              <a href={e.url} target="_blank" rel="noopener noreferrer">
                원문 보기 ↗
              </a>
            ) : (
              <span className="muted">원문 링크 없음{e.source === "demo" ? " (시연 데이터)" : ""}</span>
            )}
          </li>
        ))}
      </ol>
      {item.current.by_source && Object.keys(item.current.by_source).length > 0 && (
        <p className="muted">
          수집처별 게시물(최근): {Object.entries(item.current.by_source).map(([s, n]) => `${s === "demo" ? "시연 데이터" : s} ${n}건`).join(", ")}
          {item.current.ad_posts > 0 && ` · 광고·협찬 표시 ${item.current.ad_posts}건 포함`}
        </p>
      )}
    </div>
  );
}

function FoodCard({ item, summary, onFavorite }) {
  const [explanation, setExplanation] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [open, setOpen] = useState(false);
  const excluded = item.rank_excluded;

  useEffect(() => {
    let alive = true;
    request(`/api/trends/foods/${item.food_id}/explanation`)
      .then((d) => alive && setExplanation(d))
      .catch(() => alive && setExplanation({ status: "failed", error: "network" }));
    return () => {
      alive = false;
    };
  }, [item.food_id]);

  async function toggleDetail() {
    const next = !open;
    setOpen(next);
    if (next && evidence === null) {
      try {
        setEvidence((await request(`/api/trends/foods/${item.food_id}/evidence`)).items);
      } catch {
        setEvidence([]);
      }
    }
  }
  async function reExplain(refresh) {
    setExplanation(await request(`/api/trends/foods/${item.food_id}/explanation`, { method: "POST", body: { refresh } }));
  }

  return (
    <li className="trend-card card">
      <div className="trend-head">
        <div>
          <h3 className="trend-name">
            {item.name}
            {item.brand && <span className="muted"> · {item.brand}</span>}
          </h3>
          <span className="muted">{item.kind === "product" ? "개별 상품" : "식품 유형"}</span>
        </div>
        <Change item={item} />
      </div>
      <p className="trend-counts">
        최근 <strong>{count(item.current.posts)}건</strong> · 이전 <strong>{count(item.previous.posts)}건</strong>
        <span className="muted"> · {item.current.accounts == null ? "작성 계정 수는 확인하지 못했어요" : `작성 계정 ${item.current.accounts}곳`}</span>
      </p>
      <p className="muted trend-basis">수집 게시물 기준{item.official_count > 0 ? ` · 공식 발표 ${item.official_count}건 별도` : ""}</p>
      <Spark daily={item.daily} />
      {excluded && <p className="trend-excluded">증가 순위에서 뺐어요: {excluded}</p>}
      <Explanation foodId={item.food_id} state={explanation} onChange={setExplanation} />
      <div className="trend-actions">
        <button type="button" className="text-button" aria-expanded={open} onClick={toggleDetail}>
          근거 콘텐츠 보기 {open ? "▴" : "▾"}
        </button>
        <button type="button" className={`button ${item.favorite ? "" : "secondary"}`} aria-pressed={item.favorite} onClick={() => onFavorite(item)}>
          {item.favorite ? "★ 저장됨" : "☆ 관심 식품 저장"}
        </button>
      </div>
      {open && <Detail item={item} explanation={explanation} evidence={evidence} onExplain={reExplain} />}
    </li>
  );
}

export default function Trends() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [sort, setSort] = useState("growth");
  const [onlySaved, setOnlySaved] = useState(false);

  const load = useCallback(() => {
    setFailed(false);
    request("/api/trends")
      .then(setData)
      .catch(() => setFailed(true));
  }, []);
  useEffect(load, [load]);

  async function favorite(item) {
    const was = item.favorite;
    setData((d) => ({ ...d, items: d.items.map((i) => (i.food_id === item.food_id ? { ...i, favorite: !was } : i)) })); // 먼저 보여 주고, 저장에 실패하면 되돌립니다
    try {
      await request(`/api/trends/favorites/${item.food_id}`, { method: was ? "DELETE" : "POST" });
    } catch {
      setData((d) => ({ ...d, items: d.items.map((i) => (i.food_id === item.food_id ? { ...i, favorite: was } : i)) }));
    }
  }

  if (failed) {
    return (
      <section>
        <h1 className="page-title">요즘 뜨는 식품</h1>
        <p className="card-note">불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.</p>
        <button type="button" className="button secondary" onClick={load}>
          다시 시도
        </button>
      </section>
    );
  }
  if (!data) return <p className="empty-note">불러오는 중…</p>;

  const mode = MODE[data.mode] ?? MODE.none;
  const byId = Object.fromEntries(data.items.map((i) => [i.food_id, i]));
  const order = sort === "growth" ? data.rank.growth : data.rank.mentions;
  let shown = order.map((id) => byId[id]).filter(Boolean);
  const outOfRank = sort === "growth" ? data.items.filter((i) => i.rank_excluded) : [];
  if (onlySaved) shown = shown.filter((i) => i.favorite);
  const status = data.status;
  const gaps = (s) => [...s.missing_days.map((d) => `${monthDay(d)} 미수집`), ...s.failed_days.map((d) => `${monthDay(d)} 수집 실패`)];

  return (
    <section className="trends-page">
      <header className="trend-top">
        <h1 className="page-title">요즘 뜨는 식품</h1>
        <p className={`trend-mode ${mode.tone}`}>
          <strong>{mode.text}</strong>
          {mode.note && <span> · {mode.note}</span>}
        </p>
        <dl className="trend-meta">
          <div>
            <dt>분석 기간</dt>
            <dd>
              최근 완료된 7일 {rangeText(data.period.current)} 과 직전 7일 {rangeText(data.period.previous)} 비교 (한국 시간)
            </dd>
          </div>
          <div>
            <dt>데이터 출처</dt>
            <dd>
              {data.sources.length ? data.sources.map((s) => (s === "demo" ? "시연 데이터(가짜)" : s)).join(", ") : "없음"}
              {data.scope.length > 0 && ` · 수집 범위: ${data.scope.join(" / ")}`}
            </dd>
          </div>
          <div>
            <dt>마지막 갱신</dt>
            <dd>{data.last_collected ? data.last_collected.slice(0, 16).replace("T", " ") + " (한국 시간)" : "—"}</dd>
          </div>
        </dl>
        <p className="muted">게시물 언급량이에요. 검색 관심도와는 다른 지표예요. 실제 SNS 전체 언급량이 아니라 수집한 게시물 기준이에요.</p>
      </header>

      {(!status.current.complete || !status.previous.complete || status.scope_mismatch) && data.sources.length > 0 && (
        <div className="trend-warn" role="status">
          {!status.current.complete && <p>최근 기간에 수집하지 못한 날이 있어요: {gaps(status.current).join(", ")}. 못 가져온 날은 0건으로 세지 않아요.</p>}
          {!status.previous.complete && <p>직전 기간에 수집하지 못한 날이 있어요: {gaps(status.previous).join(", ")}. 그래서 증가 순위를 보류했어요.</p>}
          {status.scope_mismatch && <p>두 기간의 수집 범위가 달라서 증가 순위를 보류했어요.</p>}
        </div>
      )}

      <div className="trend-controls">
        <div className="trend-sort" role="group" aria-label="정렬">
          {[["growth", "관심 증가순"], ["mentions", "언급량순"]].map(([key, label]) => (
            <button key={key} type="button" className={`settings-tab${sort === key ? " on" : ""}`} aria-pressed={sort === key} onClick={() => setSort(key)}>
              {label}
            </button>
          ))}
        </div>
        <label className="trend-saved">
          <input type="checkbox" checked={onlySaved} onChange={(e) => setOnlySaved(e.target.checked)} /> 저장한 식품만
        </label>
      </div>

      {shown.length === 0 && (
        <p className="card-note">
          {data.items.length === 0 ? "보여 줄 식품이 없어요." : onlySaved ? "저장한 식품이 없어요." : sort === "growth" ? "지금은 증가 순위로 보여 줄 식품이 없어요. 아래에서 이유를 확인해 보세요." : "보여 줄 식품이 없어요."}
        </p>
      )}
      <ul className="trend-grid">
        {shown.map((item) => (
          <FoodCard key={item.food_id} item={item} summary={data} onFavorite={favorite} />
        ))}
      </ul>

      {outOfRank.length > 0 && (
        <details className="trend-out">
          <summary>증가 순위에서 뺀 식품 {outOfRank.length}개와 이유</summary>
          <ul className="trend-grid">
            {outOfRank
              .filter((i) => !onlySaved || i.favorite)
              .map((item) => (
                <FoodCard key={item.food_id} item={item} summary={data} onFavorite={favorite} />
              ))}
          </ul>
        </details>
      )}
      <p className="card-note">외부 관심만으로 발주를 정하지 마세요. 이 탭은 우리 점포의 상품·매출과 아직 연결돼 있지 않고, 발주 수량을 권하지 않아요.</p>
    </section>
  );
}
