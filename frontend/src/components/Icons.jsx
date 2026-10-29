import { Link } from "react-router-dom";

// 한 종류의 선형 아이콘(두께 1.75, 둥근 끝)으로 통일합니다.
function Svg({ children, size = 18, className = "" }) {
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const ChevronRight = (props) => (
  <Svg {...props}>
    <path d="M9 6l6 6-6 6" />
  </Svg>
);

export const ChevronDown = (props) => (
  <Svg {...props}>
    <path d="M6 9l6 6 6-6" />
  </Svg>
);

export const AlertTriangle = (props) => (
  <Svg {...props}>
    <path d="M12 4L3 20h18L12 4z" />
    <path d="M12 10v4.5" />
    <path d="M12 17.5v.01" />
  </Svg>
);

// 링크는 밑줄 대신 문구 + 작은 화살표로 표현합니다.
export function ArrowLink({ to, children }) {
  return (
    <Link className="text-link" to={to}>
      {children}
      <ChevronRight size={16} />
    </Link>
  );
}
