import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { fleetGrafanaLink } from "../lib/grafana";

const NAV_ITEMS: { to: string; label: string; ready: boolean; administer?: boolean }[] = [
  { to: "/overview", label: "통합 현황", ready: true },
  { to: "/stations", label: "관측소", ready: true },
  { to: "/edges", label: "Edge Collector", ready: true },
  { to: "/profiles", label: "프로파일", ready: true },
  { to: "/incidents", label: "장애", ready: true },
  { to: "/settings", label: "설정", ready: true, administer: true },
  { to: "/contracts", label: "표준 Metric", ready: true },
];

export function Layout() {
  const { user, can, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <strong>관측소 SOH 모니터링</strong>
          <span>Centaur CTR 1차 대상</span>
        </div>
        <nav className="nav">
          {NAV_ITEMS.filter((item) => !item.administer || can("administer")).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "active" : undefined)}
            >
              <span>{item.label}</span>
              {!item.ready && <span className="pending">준비 중</span>}
            </NavLink>
          ))}
          <a href={fleetGrafanaLink()} target="_blank" rel="noreferrer">
            <span>Grafana</span>
          </a>
        </nav>
        <div className="sidebar-user">
          <div>
            <strong>{user?.displayName}</strong>
            <span className="muted">{user?.role}</span>
          </div>
          <button
            className="btn ghost"
            type="button"
            onClick={async () => {
              await logout();
              navigate("/login", { replace: true });
            }}
          >
            로그아웃
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
