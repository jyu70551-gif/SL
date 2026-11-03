// 편의점 앱이라는 것을 알려 주는 장식 그림들. 직접 그린 둥근 도형이고 특정 회사의 상표나 로고는 쓰지 않습니다.
// 모두 화면 읽기 프로그램에는 숨깁니다. (aria-hidden)
const PURPLE = "#5b2a9d";
const SOFT = "#7a45c2";
const DEEP = "#3d1a70";
const LIME = "#a8d52c";
const GLASS = "#f6f3ff";
const FRAME = "#cbbfee";
const LEAF = "#8fd16a";
const LEAF_DARK = "#6fbf73";
const SKIN = "#ffe3c9";
const PINK = "#ef6f8f";
const BLUE = "#5aa0e6";
const YELLOW = "#f4d03f";
const ORANGE = "#f39c3d";
const FONT = "Pretendard Variable, Pretendard, sans-serif";

// 웃는 얼굴 (두 눈과 입)
function Face({ cx, cy, s = 1, color = DEEP }) {
  return (
    <g>
      <circle cx={cx - 6 * s} cy={cy} r={2.3 * s} fill={color} />
      <circle cx={cx + 6 * s} cy={cy} r={2.3 * s} fill={color} />
      <path d={`M${cx - 4 * s} ${cy + 5 * s} q${4 * s} ${4.5 * s} ${8 * s} 0`} fill="none" stroke={color} strokeWidth={2 * s} strokeLinecap="round" />
    </g>
  );
}

// 선반 위 둥근 상품들 (폭, 높이, 색)
function Shelf({ x, y, items }) {
  let cursor = x;
  return (
    <g>
      {items.map(([w, h, color], i) => {
        const item = <rect key={i} x={cursor} y={y - h} width={w} height={h} rx={Math.min(w, h) / 2.4} fill={color} />;
        cursor += w + 5;
        return item;
      })}
      <rect x={x - 5} y={y} width={cursor - x + 5} height="5" rx="2.5" fill={FRAME} />
    </g>
  );
}

function Bush({ cx, cy, r = 22 }) {
  return (
    <g>
      <circle cx={cx - r * 0.7} cy={cy} r={r * 0.75} fill={LEAF_DARK} />
      <circle cx={cx + r * 0.7} cy={cy} r={r * 0.75} fill={LEAF_DARK} />
      <circle cx={cx} cy={cy - r * 0.35} r={r} fill={LEAF} />
    </g>
  );
}

function Cloud({ x, y, s = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`} fill="#fff" opacity="0.92">
      <circle cx="0" cy="0" r="18" />
      <circle cx="22" cy="-10" r="22" />
      <circle cx="48" cy="0" r="17" />
      <rect x="-18" y="0" width="84" height="18" rx="9" />
    </g>
  );
}

// 가게 건물 (600x360 안에 그려지고, 길은 양옆으로 끝까지 이어집니다)
function Shop() {
  return (
    <g fontFamily={FONT}>
      {/* 지붕 위 간판 */}
      <rect x="150" y="14" width="300" height="66" rx="33" fill="#fff" stroke={LIME} strokeWidth="9" />
      <text x="300" y="60" textAnchor="middle" fontSize="34" fontWeight="800" fill={PURPLE}>
        편의점
      </text>
      <circle cx="186" cy="47" r="3.5" fill={LIME} />
      <circle cx="414" cy="47" r="3.5" fill={LIME} />

      {/* 건물 */}
      <rect x="50" y="92" width="500" height="212" rx="38" fill={PURPLE} />
      {/* 물결 차양 */}
      <rect x="50" y="112" width="500" height="34" fill={SOFT} />
      {Array.from({ length: 10 }, (_, i) => (
        <circle key={i} cx={75 + i * 50} cy="146" r="25" fill={i % 2 ? "#fff" : LIME} />
      ))}
      <rect x="50" y="112" width="500" height="16" rx="8" fill={SOFT} />
      <text x="300" y="126" textAnchor="middle" fontSize="13" fontWeight="800" fill="#fff" opacity="0.9">
        24시간 열려 있어요
      </text>

      {/* 유리창 */}
      <rect x="70" y="176" width="460" height="116" rx="26" fill={GLASS} stroke={FRAME} strokeWidth="4" />
      <line x1="200" y1="176" x2="200" y2="292" stroke={FRAME} strokeWidth="4" />
      <line x1="340" y1="176" x2="340" y2="292" stroke={FRAME} strokeWidth="4" />
      <line x1="470" y1="176" x2="470" y2="292" stroke={FRAME} strokeWidth="4" />

      {/* 왼쪽 선반 */}
      <Shelf x={84} y={214} items={[[18, 28, LIME], [18, 22, PINK], [20, 30, YELLOW], [16, 24, PURPLE], [20, 26, BLUE]]} />
      <Shelf x={84} y={252} items={[[24, 26, ORANGE], [18, 30, PURPLE], [22, 22, PINK], [18, 28, LIME]]} />
      <Shelf x={84} y={290} items={[[26, 30, BLUE], [20, 22, YELLOW], [24, 28, PURPLE], [20, 24, PINK]]} />

      {/* 가운데 음료 냉장고 */}
      <rect x="212" y="184" width="116" height="102" rx="18" fill="#e7f0ff" stroke="#b9cdf0" strokeWidth="3" />
      {[224, 246, 268, 290].map((x, i) => (
        <rect key={x} x={x} y={i % 2 ? 198 : 192} width="14" height={i % 2 ? 30 : 36} rx="7" fill={[LIME, PINK, YELLOW, PURPLE][i]} />
      ))}
      {[224, 246, 268, 290].map((x, i) => (
        <rect key={`b${x}`} x={x} y={i % 2 ? 248 : 242} width="14" height={i % 2 ? 30 : 36} rx="7" fill={[BLUE, LIME, PURPLE, ORANGE][i]} />
      ))}
      <line x1="212" y1="236" x2="328" y2="236" stroke="#b9cdf0" strokeWidth="3" />

      {/* 둥근 문 */}
      <path d="M352 292 V224 a54 54 0 0 1 108 0 V292 z" fill="#fff" opacity="0.75" stroke={PURPLE} strokeWidth="4" />
      <line x1="406" y1="170" x2="406" y2="292" stroke={PURPLE} strokeWidth="4" />
      <rect x="395" y="228" width="5" height="32" rx="2.5" fill={PURPLE} />
      <rect x="412" y="228" width="5" height="32" rx="2.5" fill={PURPLE} />
      <rect x="378" y="190" width="56" height="22" rx="11" fill={LIME} />
      <text x="406" y="206" textAnchor="middle" fontSize="12.5" fontWeight="800" fill="#2a0f57">
        OPEN
      </text>

      {/* 오른쪽 작은 창: 계산대와 점원 */}
      <rect x="484" y="262" width="34" height="30" rx="8" fill={PURPLE} />
      <circle cx="501" cy="232" r="14" fill={SKIN} />
      <Face cx={501} cy={231} s={0.9} />
      <path d="M487 226 a14 12 0 0 1 28 0 z" fill={LIME} />

      {/* 길과 보도 */}
      <rect x="-1200" y="300" width="3000" height="60" fill="#d6cdf1" />
      <rect x="-1200" y="300" width="3000" height="8" fill="#c3b7ea" />
      {[40, 150, 260, 370, 480].map((x) => (
        <rect key={x} x={x} y="336" width="56" height="7" rx="3.5" fill="#fff" opacity="0.75" />
      ))}

      {/* 양옆 덤불 */}
      <Bush cx={26} cy={292} />
      <Bush cx={578} cy={292} r={20} />

      {/* 장바구니 */}
      <path d="M76 322 h70 l-8 30 h-54 z" fill={LIME} />
      <path d="M90 322 q21 -28 42 0" fill="none" stroke={DEEP} strokeWidth="4" strokeLinecap="round" />
      <circle cx="98" cy="319" r="9" fill={ORANGE} />
      <circle cx="116" cy="314" r="9" fill={PINK} />
      <rect x="124" y="302" width="14" height="24" rx="7" fill={PURPLE} />

      {/* 상자 */}
      <rect x="236" y="324" width="52" height="28" rx="8" fill={PURPLE} />
      <rect x="242" y="298" width="42" height="26" rx="8" fill={DEEP} />
      <rect x="250" y="333" width="36" height="6" rx="3" fill={LIME} />
      <rect x="254" y="307" width="26" height="6" rx="3" fill={LIME} />

      {/* 세워 둔 간판 */}
      <rect x="520" y="262" width="40" height="62" rx="14" fill="#fff" stroke={PURPLE} strokeWidth="4" />
      <circle cx="540" cy="284" r="10" fill={LIME} />
      <text x="540" y="312" textAnchor="middle" fontSize="12" fontWeight="800" fill={PURPLE}>
        24h
      </text>
      <rect x="533" y="324" width="14" height="14" fill={PURPLE} />
      <rect x="521" y="336" width="38" height="7" rx="3.5" fill={PURPLE} />
    </g>
  );
}

function Shopper({ x, y, body, hat }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <ellipse cx="0" cy="62" rx="22" ry="5" fill="#000" opacity="0.08" />
      <rect x="-14" y="30" width="10" height="32" rx="5" fill={DEEP} />
      <rect x="4" y="30" width="10" height="32" rx="5" fill={DEEP} />
      <rect x="-20" y="2" width="40" height="42" rx="18" fill={body} />
      <circle cx="0" cy="-14" r="19" fill={SKIN} />
      <path d="M-19 -16 a19 17 0 0 1 38 0 z" fill={hat} />
      <Face cx={0} cy={-11} s={0.95} />
    </g>
  );
}

// 가게 하나만 있는 그림. fill이면 부모가 정해 준 빈 공간의 바닥에 붙여 통째로 보여 주고, 아니면 폭에 맞춥니다.
export default function StoreScene({ fill = false }) {
  return (
    <div className={fill ? "store-scene fill" : "store-scene"} aria-hidden="true">
      <svg viewBox="0 0 600 360" preserveAspectRatio={fill ? "xMidYMax meet" : "xMidYMid meet"} focusable="false">
        <Cloud x={70} y={34} s={0.7} />
        <Cloud x={470} y={26} s={0.6} />
        <Shop />
      </svg>
    </div>
  );
}

// 홈 맨 아래의 넓은 동네 풍경: 가게, 나무, 가로등, 자판기, 벤치, 손님들. 컴퓨터 화면에서만 보입니다.
export function StreetScene() {
  return (
    <div className="street-scene" aria-hidden="true">
      <svg viewBox="0 0 1200 360" preserveAspectRatio="xMidYMax meet" focusable="false">
        {/* 멀리 둥근 언덕 */}
        <circle cx="130" cy="330" r="130" fill="#ddd5f6" />
        <circle cx="1070" cy="340" r="150" fill="#ddd5f6" />
        <circle cx="620" cy="360" r="160" fill="#e2dbf8" />
        <Cloud x={170} y={60} s={1} />
        <Cloud x={930} y={44} s={0.85} />
        <Cloud x={620} y={20} s={0.55} />
        <circle cx="1090" cy="62" r="22" fill="#fff" opacity="0.9" />
        <circle cx="1100" cy="56" r="19" fill="#e8e2fb" />

        {/* 가게 */}
        <g transform="translate(300 0)">
          <Shop />
        </g>

        {/* 왼쪽 나무 */}
        <g>
          <rect x="116" y="236" width="16" height="70" rx="8" fill="#a9795a" />
          <circle cx="124" cy="216" r="46" fill={LEAF} />
          <circle cx="92" cy="240" r="30" fill={LEAF_DARK} />
          <circle cx="158" cy="238" r="30" fill={LEAF_DARK} />
          <rect x="206" y="262" width="12" height="44" rx="6" fill="#a9795a" />
          <circle cx="212" cy="246" r="30" fill={LEAF} />
        </g>
        <Shopper x={246} y={248} body={PINK} hat={PURPLE} />

        {/* 오른쪽 가로등, 벤치, 자판기 */}
        <g>
          <rect x="934" y="150" width="9" height="156" rx="4.5" fill={DEEP} />
          <circle cx="938" cy="144" r="18" fill={LIME} />
          <circle cx="938" cy="144" r="30" fill={LIME} opacity="0.22" />
          <rect x="982" y="276" width="86" height="12" rx="6" fill={PURPLE} />
          <rect x="988" y="256" width="74" height="10" rx="5" fill={SOFT} />
          <rect x="992" y="288" width="8" height="18" rx="4" fill={DEEP} />
          <rect x="1050" y="288" width="8" height="18" rx="4" fill={DEEP} />
          <rect x="1090" y="196" width="76" height="110" rx="20" fill={PURPLE} />
          <rect x="1100" y="208" width="56" height="52" rx="12" fill={GLASS} />
          {[1106, 1124, 1142].map((x, i) => (
            <rect key={x} x={x} y="216" width="12" height="18" rx="6" fill={[LIME, PINK, BLUE][i]} />
          ))}
          {[1106, 1124, 1142].map((x, i) => (
            <rect key={`c${x}`} x={x} y="238" width="12" height="16" rx="6" fill={[YELLOW, BLUE, LIME][i]} />
          ))}
          <rect x="1106" y="270" width="44" height="22" rx="8" fill={LIME} />
        </g>
        <Shopper x={880} y={248} body={LIME} hat={DEEP} />
        <Bush cx={1000} cy={300} r={16} />
        <Bush cx={60} cy={298} r={18} />
      </svg>
    </div>
  );
}

// 요약 띠 가운데의 작은 편의점 물건들: 컵라면, 삼각김밥, 우유, 커피. 얼굴이 있는 둥근 모양입니다.
export function ShelfObjects() {
  return (
    <svg className="shelf-objects" viewBox="0 0 300 96" aria-hidden="true" focusable="false">
      <rect x="0" y="86" width="300" height="6" rx="3" fill={FRAME} />
      {/* 컵라면 */}
      <path d="M14 38 h56 l-8 48 h-40 z" fill={LIME} />
      <rect x="9" y="28" width="66" height="12" rx="6" fill="#fff" stroke={FRAME} strokeWidth="2.5" />
      <Face cx={42} cy={60} s={1.1} />
      <path d="M30 22 q5 -11 0 -20 M46 22 q5 -11 0 -20" fill="none" stroke={FRAME} strokeWidth="3.5" strokeLinecap="round" />
      {/* 삼각김밥 */}
      <path d="M104 86 Q104 82 108 70 L128 30 Q132 24 136 30 L156 70 Q160 82 160 86 z" fill="#fff" stroke={FRAME} strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M112 86 L132 52 L152 86 z" fill={PURPLE} />
      <Face cx={132} cy={70} s={0.95} color="#fff" />
      {/* 우유 */}
      <path d="M184 86 V44 q0 -4 3 -8 l8 -10 h24 l8 10 q3 4 3 8 V86 z" fill="#fff" stroke={FRAME} strokeWidth="2.5" strokeLinejoin="round" />
      <rect x="184" y="52" width="46" height="22" fill={BLUE} />
      <Face cx={207} cy={63} s={0.8} color="#fff" />
      {/* 커피 */}
      <path d="M248 40 h42 l-6 46 h-30 z" fill="#f4e6d6" stroke={FRAME} strokeWidth="2.5" strokeLinejoin="round" />
      <rect x="244" y="30" width="50" height="12" rx="6" fill={PURPLE} />
      <rect x="252" y="52" width="34" height="18" rx="9" fill={LIME} />
      <Face cx={269} cy={61} s={0.7} color={DEEP} />
    </svg>
  );
}

// 카드 모서리에 앉는 작은 마스코트: 둥근 라임색 얼굴에 보라 모자.
export function Mascot({ className = "card-mascot" }) {
  return (
    <svg className={className} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <circle cx="32" cy="36" r="24" fill={LIME} />
      <path d="M12 30 a20 18 0 0 1 40 0 z" fill={PURPLE} />
      <rect x="8" y="28" width="48" height="7" rx="3.5" fill={DEEP} />
      <circle cx="24" cy="42" r="3" fill={DEEP} />
      <circle cx="40" cy="42" r="3" fill={DEEP} />
      <path d="M26 48 q6 6 12 0" fill="none" stroke={DEEP} strokeWidth="3" strokeLinecap="round" />
      <circle cx="17" cy="47" r="4" fill={PINK} opacity="0.55" />
      <circle cx="47" cy="47" r="4" fill={PINK} opacity="0.55" />
    </svg>
  );
}
