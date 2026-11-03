import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { request } from "../api.js";

const TABS = [
  { to: "/", label: "홈", end: true },
  { to: "/upload", label: "파일 올리기" },
  { to: "/trends", label: "요즘 뜨는 식품" },
  { to: "/settings", label: "설정" },
];

export default function Layout() {
  // 시연용 가짜 데이터가 섞인 랩 서버일 때만 맨 위에 알립니다. (실제 매출로 착각하지 않게)
  const [lab, setLab] = useState(false);
  useEffect(() => {
    request("/api/health")
      .then((body) => setLab(Boolean(body.lab)))
      .catch(() => setLab(false));
  }, []);

  // 처음 로그인했는데 점포를 등록한 적도, 건너뛴 적도 없으면 홈 대신 "처음 설정"으로 보냅니다. (한 번만 확인)
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    if (location.pathname !== "/") return;
    let alive = true;
    request("/api/settings/setup")
      .then((setup) => alive && setup.needs_setup && navigate("/setup", { replace: true }))
      .catch(() => {});
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app-shell">
      {lab && (
        <div className="lab-banner" role="status">
          시연용 데이터예요. 가짜 숫자가 섞여 있어서 실제 매출이 아니에요.
        </div>
      )}
      <nav className="tab-bar" aria-label="메뉴">
        <span className="brand" aria-hidden="true">
          SL
        </span>
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
      {/* 컴퓨터 화면에서는 홈만 2단으로 넓게 씁니다. 나머지 화면은 읽기 좋은 폭으로 가운데에 둡니다. */}
      <main className={["/", "/trends"].includes(location.pathname) ? "app-main wide" : "app-main"}>
        <Outlet />
      </main>
    </div>
  );
}
