import { useCallback, useEffect, useState } from "react";
import { api, AuthError, type Dashboard, type Me, wsUrl } from "./api/client";
import { ConfirmModal } from "./components/Confirm";
import { AuditPage } from "./pages/Audit";
import { ComposePage } from "./pages/Compose";
import { DashboardPage } from "./pages/Dashboard";
import { DiagnosticsPage, SettingsPage } from "./pages/Diagnostics";
import { FilesPage } from "./pages/Files";
import { FoundationPage } from "./pages/Foundation";
import { LoginPage } from "./pages/Login";
import { LogsPage } from "./pages/Logs";
import { ModulesPage } from "./pages/Modules";
import { OperatorsPage } from "./pages/Operators";
import { SetupWizard } from "./pages/SetupWizard";
import { SniffPage } from "./pages/Sniff";
import { VariablesPage } from "./pages/Variables";

const NAV: { id: string; label: string; admin?: boolean }[] = [
  { id: "compose", label: "구성 보드" },
  { id: "dashboard", label: "대시보드" },
  { id: "foundation", label: "기반 설정" },
  { id: "modules", label: "모듈 토글" },
  { id: "variables", label: "통합 변수" },
  { id: "files", label: "파일 편집" },
  { id: "logs", label: "로그" },
  { id: "sniff", label: "링 모니터" },
  { id: "diagnostics", label: "진단" },
  { id: "settings", label: "설정" },
  { id: "operators", label: "작업자", admin: true },
  { id: "audit", label: "이력" },
];

const ROLE_LABEL: Record<string, string> = {
  admin: "관리자",
  operator: "운영자",
  viewer: "조회자",
};

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [needBootstrap, setNeedBootstrap] = useState(false);
  const [setupComplete, setSetupComplete] = useState(false);
  const [page, setPage] = useState("setup");
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [modal, setModal] = useState<{ title: string; body: string; action: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState("");

  const showToast = useCallback((m: string) => {
    setToast(m);
    window.setTimeout(() => setToast((cur) => (cur === m ? null : cur)), 2800);
  }, []);

  const loadMe = useCallback(async () => {
    const st = await api<{ bootstrap_required: boolean }>("/api/auth/status");
    setNeedBootstrap(st.bootstrap_required);
    try {
      const who = await api<Me>("/api/auth/me");
      setMe(who);
    } catch (e) {
      if (e instanceof AuthError) setMe(null);
      else throw e;
    } finally {
      setAuthReady(true);
    }
  }, []);

  useEffect(() => {
    loadMe().catch((e: Error) => showToast(e.message));
  }, [loadMe, showToast]);

  const refresh = useCallback(() => {
    api<Dashboard>("/api/status")
      .then(setDash)
      .catch(() => setDash(null));
  }, []);

  useEffect(() => {
    if (!me) return;
    api<{ setup_complete: boolean; ew_version?: string }>("/api/setup/status")
      .then((s) => {
        setSetupComplete(s.setup_complete);
        setVersion(s.ew_version || "");
        setPage(s.setup_complete ? "compose" : "setup");
      })
      .catch((e: Error) => showToast(e.message));
  }, [me, showToast]);

  useEffect(() => {
    if (!me || !setupComplete) return;
    refresh();
    let ws: WebSocket | null = null;
    let cancelled = false;
    wsUrl("/ws/status")
      .then((url) => {
        if (cancelled) return;
        ws = new WebSocket(url);
        ws.onmessage = (ev) => {
          try {
            setDash(JSON.parse(ev.data) as Dashboard);
          } catch {
            /* ignore */
          }
        };
      })
      .catch((e: Error) => showToast(e.message));
    return () => {
      cancelled = true;
      ws?.close();
    };
  }, [me, setupComplete, refresh, showToast]);

  async function control(action: string) {
    setBusy(true);
    try {
      const data = await api<Dashboard>(`/api/control/${action}`, { method: "POST" });
      setDash(data);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      setBusy(false);
      setModal(null);
    }
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    setMe(null);
    setNeedBootstrap(false);
    await loadMe();
  }

  const running = Boolean(dash?.running);
  const later = setupComplete;
  const canControl = me?.role === "admin" || me?.role === "operator";

  if (!authReady) {
    return (
      <div className="login-wrap">
        <p className="lead">불러오는 중…</p>
      </div>
    );
  }

  if (!me) {
    return (
      <>
        <LoginPage bootstrap={needBootstrap} toast={showToast} onAuthed={() => void loadMe()} />
        {toast && <div className="toast">{toast}</div>}
      </>
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Earthworm Web Control</h1>
          <small>{version || "v8"}</small>
        </div>
        <div className="controls">
          <span className={`badge ${running ? "ok" : "bad"}`}>
            <span className="dot" />
            {running ? "startstop Alive" : "중지됨"}
          </span>
          <button
            className="primary"
            disabled={!later || running || busy || !canControl}
            onClick={() =>
              setModal({ title: "Earthworm 시작", body: "startstop 을 백그라운드로 기동합니다.", action: "start" })
            }
          >
            시작
          </button>
          <button disabled={!later || !running || busy || !canControl} onClick={() => void control("pause")}>
            일시중지
          </button>
          <button disabled={!later || !running || busy || !canControl} onClick={() => void control("resume")}>
            재개
          </button>
          <button
            className="danger"
            disabled={!later || busy || !canControl}
            onClick={() => setModal({ title: "전체 종료", body: "pau 를 보냅니다.", action: "stop" })}
          >
            전체중지
          </button>
          <span className="badge">
            {me.display_name} · {ROLE_LABEL[me.role] || me.role}
          </span>
          <button onClick={() => void logout()}>로그아웃</button>
        </div>
      </header>
      <aside className="sidebar">
        <div className="nav-label">초기 설정</div>
        <button
          className={`nav-btn ${page === "setup" ? "active" : ""}`}
          onClick={() => setPage("setup")}
        >
          마법사
        </button>
        <div className="nav-label">이후 설정</div>
        {NAV.map((n) => {
          if (n.admin && me.role !== "admin") return null;
          return (
            <button
              key={n.id}
              className={`nav-btn ${page === n.id ? "active" : ""}`}
              disabled={!later && n.id !== "audit" && n.id !== "operators"}
              onClick={() => setPage(n.id)}
            >
              {n.label}
            </button>
          );
        })}
      </aside>
      <main className="main">
        {page === "setup" && (
          <SetupWizard
            toast={showToast}
            needBootstrap={needBootstrap}
            onDone={() => {
              setSetupComplete(true);
              setPage("compose");
              refresh();
              void loadMe();
            }}
          />
        )}
        {page === "dashboard" && <DashboardPage dash={dash} toast={showToast} refresh={refresh} />}
        {page === "compose" && <ComposePage toast={showToast} running={running} me={me} />}
        {page === "foundation" && <FoundationPage toast={showToast} locked={running} />}
        {page === "modules" && <ModulesPage toast={showToast} running={running} />}
        {page === "variables" && <VariablesPage toast={showToast} />}
        {page === "files" && <FilesPage toast={showToast} />}
        {page === "logs" && <LogsPage toast={showToast} />}
        {page === "sniff" && <SniffPage toast={showToast} />}
        {page === "diagnostics" && <DiagnosticsPage toast={showToast} canUnlock={me.role === "admin"} />}
        {page === "settings" && <SettingsPage toast={showToast} />}
        {page === "operators" && me.role === "admin" && <OperatorsPage toast={showToast} />}
        {page === "audit" && <AuditPage toast={showToast} />}
      </main>
      {toast && <div className="toast">{toast}</div>}
      {modal && (
        <ConfirmModal
          title={modal.title}
          body={modal.body}
          onCancel={() => setModal(null)}
          onOk={() => void control(modal.action)}
        />
      )}
    </div>
  );
}
