import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { request } from "../api.js";
import { Card } from "./Card.jsx";
import { Mascot } from "./StoreScene.jsx";
import { CRITERIA, DayRows, SIGNAL, action, estimated, pct, reason } from "./stockText.jsx";

const UNAVAILABLE = {
  off: "AI 기능이 꺼져 있어요.",
  no_key: "AI 연결 키가 아직 없어요.",
  limit: "이번 달 AI 사용 한도에 도달했어요.",
  degraded: "AI 연결이 불안정해서 잠시 쉬고 있어요.",
  key_invalid: "AI 연결 키가 올바르지 않아요.",
};

// 오늘 만든 결과는 이 브라우저 탭에 잠깐 기억해 두었다가 홈에 다시 오면 바로 보여 줍니다. (AI를 다시 부르지 않습니다)
const STORE_KEY = "sl.aiSummary";

function dayKey() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function remembered() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
    return saved && saved.day === dayKey() && saved.data?.status === "ok" ? saved.data : null;
  } catch {
    return null;
  }
}

// 점포 위치를 바꾸면 StoreCard가 이 표시를 남깁니다. 홈에 오면 한 번 자동으로 새로 만듭니다.
const REFRESH_KEY = "sl.aiRefresh";

function takeRefreshFlag() {
  try {
    const on = sessionStorage.getItem(REFRESH_KEY) === "1";
    if (on) sessionStorage.removeItem(REFRESH_KEY);
    return on;
  } catch {
    return false;
  }
}

function remember(data) {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify({ day: dayKey(), data }));
  } catch {
    /* 저장이 막혀 있어도 화면은 정상입니다 */
  }
}

const FOCUSABLE = 'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

const longDay = (iso) => {
  const [, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${m}월 ${d}일`;
};
const clock = (iso) => new Date(iso).toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "numeric", minute: "2-digit", hour12: true });

// 외부 정보 사실 목록: 같은 사실은 한 번만 보이고, 학생 상권 사실이 있으면 거기에 이미 학교 수·거리가 들어 있으므로 '주변 시설'의 학교 줄은 빼서 같은 학교 정보가 반복되지 않게 합니다.
function dedupeFacts(facts) {
  const unique = [...new Map(facts.map((f) => [f.id, f])).values()];
  const hasStudents = unique.some((f) => f.id === "students");
  return unique.filter((f) => !(hasStudents && (f.id.startsWith("places:") || f.id.startsWith("schools:"))));
}

function FactList({ facts }) {
  const list = dedupeFacts(facts);
  const groups = [...new Set(list.map((f) => f.group))];
  return (
    <div className="suggest-facts">
      {groups.map((group) => (
        <div key={group}>
          <h4 className="ai-fact-group">{group}</h4>
          <ul className="basis-list">
            {list.filter((f) => f.group === group).map((f) => (
              <li key={f.id}>{f.text}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

// 우선 확인할 일 한 줄: 상품명 → 관측 사실 → 확인할 행동. 숫자와 문장은 서버가 계산한 식품 발주 점검 값을 그대로 풀어 쓴 것이고, 순위를 암시하지 않습니다.
function PriorityItem({ card, item, params }) {
  const [open, setOpen] = useState(false);
  const id = `why-${item?.product ?? card.title}`.replace(/\s+/g, "-");
  if (!item) {
    return (
      <li className="ai-priority">
        <strong className="ai-priority-name">{card.title}</strong>
        <p>{card.body}</p>
      </li>
    );
  }
  const sig = SIGNAL[item.signal] ?? SIGNAL.none;
  const next = action(item);
  const days = item.window_days ?? [];
  return (
    <li className="ai-priority">
      <div className="ai-priority-head">
        <strong className="ai-priority-name">{item.name}</strong>
        <span className={`stock-badge ${sig.tone}`}>{item.signal === "increase_review" && estimated(item) ? sig.guessed : sig.text}</span>
      </div>
      <p className="ai-observe">{reason(item, params)}</p>
      <p className="ai-metrics">
        소진율 {pct(item.window.sell_through_pct)} · 폐기율 {pct(item.window.waste_pct)}
      </p>
      {next && <p className="ai-action">{next}</p>}
      <button type="button" className="ai-expand" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        판단 근거 보기 <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div id={id} className="ai-why">
          <p>
            비교 기간: {days.length > 0 ? `${longDay(days[0].day)} ~ ${longDay(days[days.length - 1].day)}, ` : ""}행사 없이 판매를 마친 {item.window.days}회 (판매 {item.window.sold}/{item.window.available}, 폐기 {item.window.discarded}개)
          </p>
          <DayRows days={days} />
          {item.promo_window.days > 0 && (
            <>
              <p>
                행사 중 {item.promo_window.days}회: 소진율 {pct(item.promo_window.sell_through_pct)}, 폐기율 {pct(item.promo_window.waste_pct)}. 행사 때문이라고 확정할 수는 없어요.
              </p>
              <DayRows days={item.promo_days} />
            </>
          )}
          {CRITERIA[item.signal] && params && <p>{CRITERIA[item.signal](params)} (검증 전 초기값)</p>}
          {estimated(item) && <p>품절 시각 기록이 없어 &lsquo;다 팔렸는지&rsquo;로 추정했어요.</p>}
          {item.carryover && <p>이월 재고가 있어서 합산 소진율이 실제보다 낮게 보일 수 있어요.</p>}
          {item.dropped_mismatch > 0 && <p>재고 수량이 안 맞는 기록 {item.dropped_mismatch}건은 뺐어요.</p>}
        </div>
      )}
    </li>
  );
}

function Ideas({ ideas }) {
  const [open, setOpen] = useState(false);
  const all = ideas.flatMap((c) => c.facts);
  return (
    <section className="ai-ideas">
      <button type="button" className="ai-expand ai-expand-head" aria-expanded={open} aria-controls="ai-ideas-body" onClick={() => setOpen(!open)}>
        추가 운영 아이디어 {ideas.length}개 <span aria-hidden="true">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div id="ai-ideas-body">
          <p className="ai-note">외부 정보(날짜·방학·상권·날씨)를 참고한 아이디어이며 판매 효과는 확인되지 않았어요.</p>
          <ul className="ai-idea-list">
            {ideas.map((card) => (
              <li key={card.title}>
                <strong>{card.title}</strong>
                <p>{card.body}</p>
                <p className="ai-note">참고한 정보: {[...new Set(dedupeFacts(card.facts).map((f) => f.group))].join(" · ")}</p>
              </li>
            ))}
          </ul>
          <h4 className="ai-fact-title">참고한 외부 정보</h4>
          <p className="ai-note">이 점포의 판매 자료로 확인한 것이 아니에요.</p>
          <FactList facts={all} />
        </div>
      )}
    </section>
  );
}

// 상세 패널: 컴퓨터는 오른쪽에서 나오는 패널, 휴대폰은 전체 화면. 배경 페이지 위에 겹쳐 뜨므로(고정 위치, portal) 홈 카드 배치는 바뀌지 않습니다.
// 머리(제목·기준 정보·닫기)는 위에 고정되고 본문 한 곳만 스크롤됩니다. 닫기 버튼·Escape·바깥 클릭으로 닫고, 열려 있는 동안 배경 스크롤과 배경 키보드 이동을 막고,
// 닫으면 열었던 버튼으로 포커스를 돌려줍니다.
function DetailPanel({ onClose, returnTo, meta, children }) {
  const panelRef = useRef(null);
  useEffect(() => {
    const panel = panelRef.current;
    const root = document.getElementById("root");
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (root) root.inert = true;
    panel.querySelector(".ai-panel-close").focus();
    function onKey(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "Tab") {
        const items = [...panel.querySelectorAll(FOCUSABLE)];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      if (root) root.inert = false;
      returnTo?.focus();
    };
  }, [onClose, returnTo]);

  return createPortal(
    <div className="ai-panel-layer">
      <div className="ai-panel-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className="ai-panel" role="dialog" aria-modal="true" aria-labelledby="ai-panel-title" ref={panelRef}>
        <header className="ai-panel-head">
          <div className="ai-panel-top">
            <h2 id="ai-panel-title">AI 점검 내용</h2>
            <button type="button" className="ai-panel-close" onClick={onClose}>
              닫기 ✕
            </button>
          </div>
          {meta}
        </header>
        <div className="ai-panel-body">{children}</div>
      </aside>
    </div>,
    document.body,
  );
}

// 눌렀을 때만 AI 점검 요약을 만듭니다. 근거가 된 사실은 코드가 모은 것이고, 요약 문장만 AI가 씁니다.
// 홈 카드에는 핵심 점검 요약(최대 2개, 제목과 한 문장)만 보이고, 전체 내용·근거·추가 운영 아이디어·다시 만들기는 상세 패널에 있습니다.
export default function SuggestCard() {
  const [data, setData] = useState(remembered);
  const [state, setState] = useState(() => (remembered() ? "done" : "idle")); // idle | loading | done | error
  const [busy, setBusy] = useState(false); // 이미 결과가 있을 때 다시 만드는 중(기존 결과는 그대로 둡니다)
  const [failed, setFailed] = useState(false); // 다시 만들기가 실패(기존 결과는 그대로 둡니다)
  const [open, setOpen] = useState(false);
  const [stock, setStock] = useState(null); // 식품 발주 점검 값(패널의 상품별 행을 서버 계산값으로 채웁니다)
  const detailButton = useRef(null);
  const autoRef = useRef(false);

  useEffect(() => {
    if (autoRef.current) return;
    autoRef.current = true;
    if (takeRefreshFlag()) make(true);
  }, []);

  async function make(refresh = false) {
    const had = state === "done" && data;
    if (had) setBusy(true);
    else setState("loading");
    setFailed(false);
    try {
      const result = await request("/api/suggestions", { method: "POST", body: { refresh } });
      setData(result);
      setState("done");
      if (result.status === "ok") remember(result);
    } catch {
      if (had) setFailed(true);
      else setState("error");
    } finally {
      setBusy(false);
    }
  }

  const ok = state === "done" && data?.status === "ok";
  const cards = ok ? data.cards.slice(0, 5) : [];
  // 기억해 둔 예전 결과에는 종류 표시(kind)가 없어서, 없으면 외부 정보 아이디어로 봅니다.
  const analysis = cards.filter((card) => card.kind === "analysis");
  const ideas = cards.filter((card) => card.kind !== "analysis");
  const hasDetail = state === "done" && !!data;
  const close = () => setOpen(false);
  const sourceLabel = data?.demo ? "시연용 상품 데이터" : "우리 점포 입출고 기록";

  useEffect(() => {
    if (!ok || analysis.length === 0) return;
    let alive = true;
    request("/api/stock/summary")
      .then((s) => alive && setStock(s))
      .catch(() => alive && setStock(null)); // 못 받아도 카드의 글로 대신 보여 줍니다
    return () => {
      alive = false;
    };
  }, [ok, data]);

  const products = Object.fromEntries((stock?.products ?? []).map((p) => [p.product, p]));
  const analyzedDate = stock?.status === "ready" ? stock.date : null;
  const panelMeta = (
    <div className="ai-panel-meta">
      <p>
        {analyzedDate ? `분석 기준: ${longDay(analyzedDate)}까지의 입출고 기록` : `분석한 날: ${longDay(data?.date ?? "")}`} <span className={data?.demo ? "stock-demo" : "stock-real"}>{sourceLabel}</span>
      </p>
      <p className="ai-note">{data?.demo ? "실제 매출이 아니라 시연용 상품 데이터로 계산했어요." : "우리 점포 입출고 기록으로 계산했어요."}</p>
    </div>
  );

  return (
    <Card title="AI 점검 요약">
      <Mascot />
      {state === "idle" && (
        <>
          <p className="card-note">우리 점포 입출고 기록의 판매·품절·폐기 분석을 먼저, 날짜·방학·상권·날씨를 보고 짐작한 아이디어를 따로 정리해 드려요. 누를 때만 만들어요.</p>
          <button type="button" className="button" onClick={() => make(false)}>
            오늘 점검 요약 만들기
          </button>
        </>
      )}
      {state === "loading" && (
        <>
          <p className="card-note" role="status">살펴보고 있어요…</p>
          <button type="button" className="button" disabled aria-busy="true">
            만드는 중…
          </button>
        </>
      )}
      {state === "error" && (
        <>
          <p className="card-note" role="alert">요약을 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.</p>
          <button type="button" className="button secondary" onClick={() => make(false)}>
            다시 시도
          </button>
        </>
      )}

      {state === "done" && data?.status === "unavailable" && <p className="card-note">{UNAVAILABLE[data.state] ?? "AI를 쓸 수 없어요."} 대신 오늘 알아 둘 점은 자세히 보기에서 볼 수 있어요.</p>}
      {state === "done" && data?.status === "failed" && <p className="card-note">요약을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요. 대신 오늘 알아 둘 점은 자세히 보기에서 볼 수 있어요.</p>}

      {ok && (
        <section className="ai-summary">
          <div className="ai-section-head">
            <h3 className="group-title">점검 요약</h3>
            <span className={data.demo ? "stock-demo" : "stock-real"}>{sourceLabel}</span>
          </div>
          {analysis.length > 0 ? (
            <ol className="ai-brief">
              {analysis.slice(0, 2).map((card) => (
                <li key={card.title}>
                  <strong className="suggest-title">{card.title}</strong>
                  <p className="suggest-body">{card.short ?? card.body}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="card-note">이번에는 판매·품절·폐기 점검 항목이 없어요.{ideas.length > 0 && " 추가 운영 아이디어는 자세히 보기에 있어요."}</p>
          )}
        </section>
      )}

      {failed && (
        <p className="card-note" role="alert">
          다시 만들지 못했어요. 기존 결과는 그대로예요.
        </p>
      )}
      {hasDetail && (
        <div className="ai-actions">
          <button type="button" className="button secondary" ref={detailButton} aria-haspopup="dialog" onClick={() => setOpen(true)}>
            점검 내용 자세히 보기
          </button>
          {busy && <span className="card-note" role="status">다시 만드는 중…</span>}
        </div>
      )}

      {open && hasDetail && (
        <DetailPanel onClose={close} returnTo={detailButton.current} meta={panelMeta}>
          {ok && (
            <>
              {analysis.length > 0 && (
                <section className="ai-priorities">
                  <h3 className="ai-section-title">우선 확인할 일</h3>
                  <ul>
                    {analysis.map((card) => {
                      const code = card.facts.find((f) => f.id.startsWith("stock:"))?.id.slice(6);
                      return <PriorityItem key={card.title} card={card} item={products[code]} params={stock?.params} />;
                    })}
                  </ul>
                </section>
              )}
              {ideas.length > 0 && <Ideas ideas={ideas} />}
            </>
          )}
          {!ok && <FactList facts={data.facts ?? []} />}
          <div className="ai-regen">
            {data.generated_at && <p className="ai-note">생성 시각: {clock(data.generated_at)}</p>}
            <button type="button" className="button secondary" disabled={busy} onClick={() => make(true)}>
              {busy ? "다시 만드는 중…" : "다시 만들기"}
            </button>
            {busy && <p className="ai-note" role="status">기존 결과는 그대로 두고 새로 만들고 있어요.</p>}
            {failed && <p className="ai-note" role="alert">다시 만들지 못했어요. 기존 결과는 그대로예요.</p>}
          </div>
        </DetailPanel>
      )}
    </Card>
  );
}
