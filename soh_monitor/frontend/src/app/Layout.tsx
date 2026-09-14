import { NavLink, Outlet } from "react-router-dom";

// 화면 구성은 계획서 10절을 따른다. 아직 구현되지 않은 화면은 '준비 중' 으로 표시해
// 무엇이 남았는지 화면에서 그대로 드러나게 한다.
const NAV_ITEMS: { to: string; label: string; ready: boolean }[] = [
  { to: "/overview", label: "통합 현황", ready: false },
  { to: "/stations", label: "관측소", ready: false },
  { to: "/edges", label: "Edge Collector", ready: false },
  { to: "/profiles", label: "프로파일", ready: false },
  { to: "/incidents", label: "장애", ready: false },
  { to: "/contracts", label: "표준 Metric", ready: true },
];

export function Layout() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <strong>관측소 SOH 모니터링</strong>
          <span>Centaur CTR 1차 대상</span>
        </div>
        <nav className="nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              <span>{item.label}</span>
              {!item.ready && <span className="pending">준비 중</span>}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
