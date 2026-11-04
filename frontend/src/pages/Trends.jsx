import { useCallback, useEffect, useState } from "react";
import { request } from "../api.js";

// '요즘 뜨는 식품' 탭 (docs/trends.md 11장). 버튼을 누르면 편의점 신상 해시태그의 최근 게시물을 한 번 받아 상품 이름별 언급 게시물 수를 보여 줍니다.
// 건수는 서버가 코드로 센 값입니다. '증가'·'급상승'·'전체 인기 순위'라고 말하지 않고, 근거는 펼쳐서 봅니다. AI 설명은 만들지 않으므로 보여 주지 않습니다.
const BLOCKED = {
  no_token: "수집 설정(Apify 키)이 아직 없어서 가져올 수 없어요.",
  ai_unavailable: "AI를 지금 쓸 수 없어서 상품 이름을 찾을 수 없어요.",
  run_cap_low: "한 번에 쓸 수 있는 비용 상한이 낮아서 가져올 수 없어요. 설정(APIFY_RUN_MAX_USD)을 올려 주세요.",
};
const FAIL = {
  no_token: "수집 설정(Apify 키)이 아직 없어요.",
  ai_unavailable: "AI를 지금 쓸 수 없어요. 게시물을 받기 전에 멈춰서 비용은 들지 않았어요.",
  busy: "이미 가져오는 중이에요. 잠시 뒤 결과를 확인해 주세요.",
  monthly_limit: "이번 달 수집 한도에 닿아서 가져오지 않았어요. 다음 달에 다시 가져올 수 있어요.",
  run_cap_low: "한 번에 쓸 수 있는 비용 상한이 낮아서 가져오지 않았어요(돈은 쓰지 않았어요). 설정(APIFY_RUN_MAX_USD)을 올려 주세요.",
  timeout: "응답이 너무 늦어서 멈췄어요. 잠시 뒤 다시 눌러 주세요.",
  payment: "Apify 사용 한도나 결제 문제로 가져오지 못했어요. Apify 계정을 확인해 주세요.",
  network: "연결에 실패했어요. 잠시 뒤 다시 눌러 주세요.",
};

const kstTime = (iso) => new Date(iso + "Z").toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true });
const korDay = (iso) => {
  if (!iso) return null; // 게시일 정보가 없는 옛 저장 결과
  const [, m, d] = iso.split("-").map(Number);
  return `${m}월 ${d}일`;
};
const postedText = (iso) => (iso ? `게시일 ${korDay(iso)}` : "게시일 확인 못함");

function FoodCard({ food }) {
  const [open, setOpen] = useState(false);
  const shown = food.evidence ?? (food.links ?? []).map((url) => ({ url, text: "", posted_on: null })); // 옛 형식(링크만)도 읽습니다
  return (
    <li className="td-card">
      <h3 className="td-name">{food.name}</h3>
      <p className="td-counts">
        수집 게시물 <strong>{food.posts}건</strong> · 작성 계정 {food.accounts}곳
      </p>
      {food.safety_posts > 0 && (
        <p className="td-safety-tag">
          <span aria-hidden="true">⚠ </span>이 상품은 안전 관련 언급이 있어요(게시물 {food.safety_posts}건). 위 건수에는 세지 않았어요. 아래 &ldquo;안전 관련 언급&rdquo;에서 확인하고, 공식 공지도 확인해 주세요.
        </p>
      )}
      <button type="button" className="td-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
        근거 게시물 {food.posts}건 보기 <span aria-hidden="true">{open ? "⌃" : "›"}</span>
      </button>
      {open && (
        <div className="td-evidence">
          <p className="td-note">게시물에 쓰인 말이에요. 확인된 사실이 아니에요.{food.posts > shown.length && ` 이 중 ${shown.length}건만 보여 줘요.`}</p>
          <ul>
            {shown.map((e) => (
              <li key={e.url}>
                {e.text && <p>{e.text}</p>}
                <p className="td-note">
                  {postedText(e.posted_on)} ·{" "}
                  <a href={e.url} target="_blank" rel="noopener noreferrer">
                    원본 보기 ↗
                  </a>
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

function SafetyMentions({ snap }) {
  const list = snap.warnings ?? [];
  if (!list.length) return null;
  return (
    <details className="td-safety">
      <summary>안전 관련 언급 · 확인 필요 게시물 {snap.safety_posts}건</summary>
      <div className="td-panel">
        <p>게시물에서 회수·안전 관련 표현이 발견됐어요. 공식 확인 전 정보이며, 과거 내용이나 잘못된 정보가 포함될 수 있어요. 식약처 회수 정보나 본사 공지를 확인해 주세요. 위 식품 건수에는 세지 않았어요.</p>
        <ul>
          {list.map((w) => (
            <li key={w.url}>
              <strong>{w.foods.length ? w.foods.join(", ") : "상품 이름 미확인"}</strong>
              <p>{w.text}…</p>
              <p className="td-note">
                {postedText(w.posted_on)} ·{" "}
                <a href={w.url} target="_blank" rel="noopener noreferrer">
                  원본 보기 ↗
                </a>
              </p>
            </li>
          ))}
        </ul>
        {snap.safety_posts > list.length && <p className="td-note">이 밖에 게시물 {snap.safety_posts - list.length}건이 더 있어요.</p>}
      </div>
    </details>
  );
}

function Criteria({ data, snap }) {
  const normal = snap ? snap.unique_posts - snap.safety_posts : 0;
  return (
    <details className="td-criteria">
      <summary>수집 기준과 한계 보기</summary>
      <div className="td-panel">
        <dl>
          <dt>수집 플랫폼</dt>
          <dd>인스타그램 공개 게시물(Apify로 수집)</dd>
          {snap && (
            <>
              <dt>대상 해시태그</dt>
              <dd>{snap.tags.map((t) => `#${t}`).join(" ")}</dd>
              <dt>게시물 기간</dt>
              <dd>
                {snap.posted_range
                  ? `${korDay(snap.posted_range[0])} ~ ${korDay(snap.posted_range[1])}에 올라온 게시물이에요(해시태그별 최신 글을 받아서, 정해 둔 기간은 없어요).`
                  : "확인하지 못했어요."}
              </dd>
              <dt>수집 시각</dt>
              <dd>{kstTime(snap.collected_at)} (한국 시간)</dd>
              <dt>사용한 게시물</dt>
              <dd>
                받은 {snap.received}건 중 중복을 뺀 {snap.unique_posts}건. 식품 집계에 {normal}건, 안전 관련 언급으로 따로 본 것 {snap.safety_posts}건
              </dd>
            </>
          )}
          <dt>집계 방식</dt>
          <dd>
            AI가 글에서 상품 이름 후보만 찾고, 건수는 코드가 전체 게시물에서 다시 세요. 같은 게시물은 한 번만, 작성자는 계정 수로 따로 세요. 서로 다른 게시물 2건·계정 2곳 이상에 나온 이름만 보여요. 한 게시물에 상품이 여러 개 나오면 각각 1건으로 세요. 많이 언급된 순서로 나열했어요.
          </dd>
          <dt>수집 한도</dt>
          <dd>
            해시태그당 최대 {snap?.per_hashtag ?? "정해진 수"}건, 한 번에 최대 {data.max_results}건 · 하루 1회 · 이번 달 {data.month_used}건 / 월 한도 {data.monthly_limit}건
          </dd>
        </dl>
        <p>
          해시태그 최신 게시물 일부만 본 제한된 표본이에요. 플랫폼 전체 인기나 검색량, 실제 구매 수요를 뜻하지 않고, 내일 다시 가져오면 달라질 수 있어요. 우리 점포의 상품·매출과도 연결돼 있지 않으니 이 정보만으로 발주를 정하지 마세요.
        </p>
      </div>
    </details>
  );
}

export default function Trends() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setFailed(false);
    request("/api/trends/today")
      .then(setData)
      .catch(() => setFailed(true));
  }, []);
  useEffect(load, [load]);

  async function collect() {
    setBusy(true);
    setError("");
    try {
      setData(await request("/api/trends/today/collect", { method: "POST" }));
    } catch (e) {
      setError(FAIL[e?.detail?.code] ?? "가져오지 못했어요. 잠시 뒤 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  const head = (
    <>
      <h1 className="page-title">요즘 뜨는 식품</h1>
      <p className="td-lead">최근 수집한 인스타그램 게시물에서 발견한 편의점 식품이에요.</p>
    </>
  );

  if (failed) {
    return (
      <section className="td-page">
        {head}
        <p className="td-note">불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.</p>
        <button type="button" className="button secondary" onClick={load}>
          다시 시도
        </button>
      </section>
    );
  }
  if (!data) {
    return (
      <section className="td-page" aria-busy="true">
        {head}
        <p className="td-note">불러오는 중…</p>
      </section>
    );
  }

  const snap = data.snapshot;
  return (
    <section className="td-page">
      {head}
      <div className="td-status">
        <p>
          {snap ? (
            <>
              마지막 갱신: {kstTime(snap.collected_at)} · 수집 게시물 {snap.unique_posts}건 <span className="td-chip">인스타그램 실제 수집</span>
            </>
          ) : (
            "아직 가져오지 않았어요."
          )}
        </p>
        {data.can_collect || busy ? (
          <button type="button" className="button" disabled={busy} aria-busy={busy} onClick={collect}>
            {busy ? "가져오는 중…" : error ? "다시 시도" : "최신 식품 살펴보기"}
          </button>
        ) : data.blocked === "done_today" ? (
          <p className="td-done">
            <strong>✓ 오늘 수집 완료</strong> · 다음 수집은 내일 할 수 있어요(하루 1회).
          </p>
        ) : (
          <p className="td-note">{BLOCKED[data.blocked]}</p>
        )}
        {busy && <p className="td-note">게시물을 받아 분석하는 중이에요. 1~2분 걸릴 수 있어요.</p>}
        {error && (
          <p className="td-error" role="alert">
            {error}
          </p>
        )}
      </div>

      {!snap && <p className="td-note">버튼을 누르면 편의점 신상 해시태그의 최근 게시물을 한 번 받아 와요.</p>}
      {snap && (snap.items.length === 0 ? (
        <p className="td-note">서로 다른 계정 두 곳 이상이 두 번 이상 언급한 식품을 찾지 못했어요.</p>
      ) : (
        <ul className="td-grid">
          {snap.items.map((f) => (
            <FoodCard key={f.name} food={f} />
          ))}
        </ul>
      ))}

      {snap && <SafetyMentions snap={snap} />}
      <Criteria data={data} snap={snap} />
    </section>
  );
}
