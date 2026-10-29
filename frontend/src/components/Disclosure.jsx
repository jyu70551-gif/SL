import { useState } from "react";
import { ChevronDown } from "./Icons.jsx";

// 간결한 펼치기 행. 기본은 접혀 있고, 눌러서 근거를 단계적으로 봅니다.
export default function Disclosure({ label, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="disclosure">
      <button type="button" className="disclosure-row" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span>{label}</span>
        <ChevronDown className={open ? "chev open" : "chev"} />
      </button>
      {open && <div className="disclosure-body">{children}</div>}
    </div>
  );
}
