import { useEffect, useRef, useState } from "react";
import { axisLabel, monthDay, niceAxis, won } from "../format.js";

// 그래프 스타일. 두께와 반지름은 실제 화면의 CSS px 기준입니다.
// 그래프를 화면 폭 그대로(1단위 = 1px) 그리고 직접 만든 SVG라서, 차트 라이브러리의 기본 스타일이 덮어쓰지 않습니다.
export const CHART_STYLE = {
  actual: { stroke: "#969FFF", width: 1.5 },
  baseline: { stroke: "#B1B8CA", width: 1, dash: "4 4" },
  gridH: { stroke: "#394158", width: 1 }, // 가로: 금액 눈금
  gridV: { stroke: "#2B3248", width: 1 }, // 세로: 주요 날짜 눈금 (가로보다 약하게)
  dotRadius: 2,
  selected: { radius: 5, border: 2, fill: "#FFFFFF" },
  guide: { width: 1, dash: "2 3", opacity: 0.55 },
  center: { stroke: "#B1B8CA", width: 1, dash: "4 4" }, // 평소 중심값 (비교 기준선과 같은 모양)
  bound: { stroke: "#B1B8CA", width: 1, dash: "1 4", opacity: 0.8 }, // 95% 예상 범위의 위·아래
  ring: { radius: 3.5, border: 1.5, fill: "#151C2C" }, // 비교에 쓴 같은 요일
};

const H = 240;
const PAD = { left: 46, right: 22, top: 30, bottom: 30 };
const DAY = 86400000;
const LABEL_H = 18;

const toDay = (iso) => Math.round(Date.parse(`${iso}T00:00:00Z`) / DAY);

// 금액 라벨의 대략적인 가로 길이(px). 한글은 넓고 숫자는 좁습니다.
function labelWidth(text) {
  let w = 10;
  for (const ch of text) w += /[ㄱ-힝]/.test(ch) ? 12.5 : ch === " " ? 4 : 7.4;
  return w;
}

// 사각형과 선분이 겹치는지
function hitsSegment(r, [x1, y1, x2, y2]) {
  const inside = (x, y) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
  if (inside(x1, y1) || inside(x2, y2)) return true;
  const edges = [
    [r.x, r.y, r.x + r.w, r.y],
    [r.x, r.y + r.h, r.x + r.w, r.y + r.h],
    [r.x, r.y, r.x, r.y + r.h],
    [r.x + r.w, r.y, r.x + r.w, r.y + r.h],
  ];
  const ccw = (ax, ay, bx, by, cx, cy) => (cy - ay) * (bx - ax) > (by - ay) * (cx - ax);
  return edges.some(
    ([ax, ay, bx, by]) =>
      ccw(ax, ay, x1, y1, x2, y2) !== ccw(bx, by, x1, y1, x2, y2) &&
      ccw(ax, ay, bx, by, x1, y1) !== ccw(ax, ay, bx, by, x2, y2),
  );
}

// 선택한 점의 금액 라벨 위치. 점·판매선·기준선·안내선·다른 점·차트 경계와 겹치지 않는 자리를 찾고,
// 모두 조금씩 겹치면 가장 덜 겹치면서 점에 가까운 자리를 고릅니다.
function placeLabel({ px, py, text, segments, dots, bounds }) {
  const w = labelWidth(text);
  const gap = 12;
  const xs = [px - w / 2, px + gap, px - gap - w, px - w + 14, px - 14]; // 가운데, 오른쪽, 왼쪽, 점이 오른쪽 끝, 점이 왼쪽 끝
  const ys = [];
  for (let k = 0; k < 4; k += 1) {
    ys.push(py - gap - LABEL_H - k * 16); // 위쪽 여러 높이
    ys.push(py + gap + k * 16); // 아래쪽 여러 높이
  }
  ys.push(py - LABEL_H / 2); // 점과 같은 높이(좌우)

  const candidates = [];
  for (const cx of xs) {
    for (const cy of ys) {
      const sideBySide = cy === py - LABEL_H / 2;
      if (sideBySide && cx !== px + gap && cx !== px - gap - w) continue; // 같은 높이는 점의 왼쪽·오른쪽만
      candidates.push({ x: Math.min(Math.max(cx, bounds.left), bounds.right - w), y: cy, w, h: LABEL_H });
    }
  }

  const inBounds = (r) => r.y >= bounds.top && r.y + r.h <= bounds.bottom;
  const score = (r) => {
    const hits = segments.filter((seg) => hitsSegment(r, seg)).length;
    const near = dots.filter(([dx, dy]) => dx >= r.x - 5 && dx <= r.x + r.w + 5 && dy >= r.y - 5 && dy <= r.y + r.h + 5).length;
    const dist = Math.hypot(r.x + r.w / 2 - px, r.y + r.h / 2 - py);
    return hits * 1000 + near * 100 + dist;
  };
  const usable = candidates.filter(inBounds);
  const pool = usable.length ? usable : candidates;
  return pool.reduce((best, r) => (score(r) < score(best) ? r : best), pool[0]);
}

// 날짜별 판매액 그래프.
// - 가로축은 실제 날짜 간격입니다. 파일을 올리지 않은 날(미수집)은 0원으로 채우지 않고 선을 이어 그리지도 않습니다.
// - 실제 0원인 날은 0원 점으로 그대로 보입니다.
// refLines: 가로 기준선 [{ value, kind: "center" | "bound" }], ringDates: 같은 요일로 표시할 날짜 목록
export default function SalesChart({ points, selectedDate, refLines = [], ringDates = [] }) {
  const wrapRef = useRef(null);
  const [width, setWidth] = useState(326);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const update = () => setWidth(Math.max(200, Math.floor(el.clientWidth)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const W = width;
  const days = points.map((p) => toDay(p.date));
  const firstDay = days[0];
  const lastDay = days[days.length - 1];
  const span = Math.max(1, lastDay - firstDay);
  const maxValue = Math.max(1, ...points.map((p) => Math.max(p.amount, p.typical ?? 0)), ...refLines.map((l) => l.value));
  const { top, ticks } = niceAxis(maxValue);

  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i) => PAD.left + (points.length === 1 ? innerW / 2 : ((days[i] - firstDay) / span) * innerW);
  const xOfDay = (d) => PAD.left + ((d - firstDay) / span) * innerW;
  const y = (v) => PAD.top + innerH - (v / top) * innerH;

  // 이어진 날짜끼리만 선을 잇습니다. (하루라도 비면 끊음, 곡선 보간 없이 직선)
  function build(valueOf) {
    let d = "";
    const segs = [];
    points.forEach((p, i) => {
      const v = valueOf(p);
      if (v == null) return;
      const connected = i > 0 && valueOf(points[i - 1]) != null && days[i] - days[i - 1] === 1;
      d += `${connected ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
      if (connected) segs.push([x(i - 1), y(valueOf(points[i - 1])), x(i), y(v)]);
    });
    return { d: d.trim(), segs };
  }
  const refSegs = refLines.map((l) => [PAD.left, y(l.value), W - PAD.right, y(l.value)]);
  const actual = build((p) => p.amount);
  const baseline = build((p) => p.typical);

  // 세로 그리드와 날짜 눈금: 주요 날짜 4~5개만
  const tickCount = Math.min(5, span + 1);
  const dateTicks = [...new Set(Array.from({ length: tickCount }, (_, k) => firstDay + Math.round((span * k) / Math.max(1, tickCount - 1))))];
  const dayLabel = (d) => monthDay(new Date(d * DAY).toISOString().slice(0, 10));

  const selectedIndex = points.findIndex((p) => p.date === selectedDate);
  const selected = selectedIndex >= 0 ? points[selectedIndex] : null;
  const plotBottom = y(0);

  let label = null;
  if (selected) {
    const px = x(selectedIndex);
    const py = y(selected.amount);
    const text = `${monthDay(selected.date)} · ${won(selected.amount)}`;
    const guide = [px, py, px, plotBottom];
    label = {
      text,
      ...placeLabel({
        px,
        py,
        text,
        segments: [...actual.segs, ...baseline.segs, ...refSegs, guide],
        dots: points.map((_, i) => [x(i), y(points[i].amount)]),
        bounds: { left: PAD.left + 2, right: W - PAD.right - 2, top: 2, bottom: plotBottom - 2 },
      }),
    };
  }

  return (
    <div ref={wrapRef} className="chart-wrap">
      <svg className="chart" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="날짜별 판매액 그래프">
        {/* 그리드는 데이터 선보다 먼저 그려서 뒤에 놓습니다. 세로는 약하게, 가로는 분명하게. */}
        {dateTicks.map((d) => (
          <line
            key={`v${d}`}
            x1={xOfDay(d)}
            x2={xOfDay(d)}
            y1={PAD.top}
            y2={plotBottom}
            stroke={CHART_STYLE.gridV.stroke}
            strokeWidth={CHART_STYLE.gridV.width}
          />
        ))}
        {ticks.map((t) => (
          <line
            key={`h${t}`}
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(t)}
            y2={y(t)}
            stroke={CHART_STYLE.gridH.stroke}
            strokeWidth={CHART_STYLE.gridH.width}
          />
        ))}

        <text x={PAD.left - 8} y={PAD.top - 14} textAnchor="end" className="chart-tick">
          (원)
        </text>
        {ticks.map((t) => (
          <text key={`t${t}`} x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="chart-tick">
            {axisLabel(t)}
          </text>
        ))}
        {dateTicks.map((d) => (
          <text
            key={`d${d}`}
            x={xOfDay(d)}
            y={H - 8}
            textAnchor="middle"
            className="chart-tick"
          >
            {dayLabel(d)}
          </text>
        ))}

        {refLines.map((l) => (
          <line
            key={`r${l.kind}${l.value}`}
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(l.value)}
            y2={y(l.value)}
            stroke={CHART_STYLE[l.kind].stroke}
            strokeWidth={CHART_STYLE[l.kind].width}
            strokeDasharray={CHART_STYLE[l.kind].dash}
            opacity={CHART_STYLE[l.kind].opacity ?? 1}
          />
        ))}
        {baseline.d && (
          <path
            d={baseline.d}
            fill="none"
            stroke={CHART_STYLE.baseline.stroke}
            strokeWidth={CHART_STYLE.baseline.width}
            strokeDasharray={CHART_STYLE.baseline.dash}
            strokeLinejoin="miter"
            vectorEffect="non-scaling-stroke"
          />
        )}
        <path
          d={actual.d}
          fill="none"
          stroke={CHART_STYLE.actual.stroke}
          strokeWidth={CHART_STYLE.actual.width}
          strokeLinejoin="miter"
          strokeLinecap="butt"
          vectorEffect="non-scaling-stroke"
        />
        {points.map((p, i) => {
          if (i === selectedIndex) return null;
          if (ringDates.includes(p.date)) {
            return (
              <circle
                key={p.date}
                cx={x(i)}
                cy={y(p.amount)}
                r={CHART_STYLE.ring.radius}
                fill={CHART_STYLE.ring.fill}
                stroke={CHART_STYLE.actual.stroke}
                strokeWidth={CHART_STYLE.ring.border}
              />
            );
          }
          return <circle key={p.date} cx={x(i)} cy={y(p.amount)} r={CHART_STYLE.dotRadius} fill={CHART_STYLE.actual.stroke} />;
        })}

        {selected && (
          <g>
            <line
              x1={x(selectedIndex)}
              x2={x(selectedIndex)}
              y1={y(selected.amount)}
              y2={plotBottom}
              stroke={CHART_STYLE.actual.stroke}
              strokeWidth={CHART_STYLE.guide.width}
              strokeDasharray={CHART_STYLE.guide.dash}
              opacity={CHART_STYLE.guide.opacity}
            />
            <circle
              cx={x(selectedIndex)}
              cy={y(selected.amount)}
              r={CHART_STYLE.selected.radius}
              fill={CHART_STYLE.selected.fill}
              stroke={CHART_STYLE.actual.stroke}
              strokeWidth={CHART_STYLE.selected.border}
            />
            <text x={label.x + label.w / 2} y={label.y + LABEL_H / 2 + 5} textAnchor="middle" className="chart-flag-label">
              {label.text}
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}

// 범례: 그래프의 선·점과 같은 색·두께·점선을 그대로 씁니다.
// kind: "line"(선) 또는 "ring"(같은 요일 점). 기본은 날짜별 판매액 그래프의 범례입니다.
const DEFAULT_LEGEND = [
  { label: "실제 판매액", kind: "line", style: CHART_STYLE.actual },
  { label: "비교 기준(같은 요일 중간값)", kind: "line", style: CHART_STYLE.baseline },
];

export function ChartLegend({ items = DEFAULT_LEGEND }) {
  return (
    <ul className="legend">
      {items.map(({ label, kind, style }) => (
        <li key={label}>
          <svg width="28" height="10" aria-hidden="true">
            {kind === "ring" ? (
              <circle
                cx="14"
                cy="5"
                r={CHART_STYLE.ring.radius}
                fill={CHART_STYLE.ring.fill}
                stroke={CHART_STYLE.actual.stroke}
                strokeWidth={CHART_STYLE.ring.border}
              />
            ) : (
              <line
                x1="0"
                x2="28"
                y1="5"
                y2="5"
                stroke={style.stroke}
                strokeWidth={style.width}
                strokeDasharray={style.dash}
                opacity={style.opacity ?? 1}
              />
            )}
          </svg>
          {label}
        </li>
      ))}
    </ul>
  );
}
