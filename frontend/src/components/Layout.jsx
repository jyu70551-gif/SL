import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "/", label: "홈", end: true },
  { to: "/upload", label: "파일 올리기" },
  { to: "/settings", label: "설정" },
];

export default function Layout() {
  return (
    <div className="app-shell">
      <main className="app-main">
        <Outlet />
      </main>
      <nav className="tab-bar" aria-label="메뉴">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) => (isActive ? "tab active" : "tab")}
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
