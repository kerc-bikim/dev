import { useCallback, useEffect, useState } from "react";
import { api, type Dashboard, wsUrl } from "./api/client";
import { ConfirmModal } from "./components/Confirm";
import { DashboardPage } from "./pages/Dashboard";
import { DiagnosticsPage, SettingsPage } from "./pages/Diagnostics";
import { FilesPage } from "./pages/Files";
import { FoundationPage } from "./pages/Foundation";
import { LogsPage } from "./pages/Logs";
import { ModulesPage } from "./pages/Modules";
import { SetupWizard } from "./pages/SetupWizard";
import { SniffPage } from "./pages/Sniff";
import { VariablesPage } from "./pages/Variables";

const NAV: { id: string; label: string }[] = [
  { id: "dashboard", label: "대시보드" },
  { id: "foundation", label: "기반 설정" },
  { id: "modules", label: "모듈 설정" },
  { id: "variables", label: "통합 변수" },
  { id: "files", label: "파일 편집" },
  { id: "logs", label: "로그" },
  { id: "sniff", label: "링 모니터" },
  { id: "diagnostics", label: "진단" },
  { id: "settings", label: "설정" },
];

export default function App() {
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

  const refresh = useCallback(() => {
    api<Dashboard>("/api/status")
      .then(setDash)
      .catch(() => setDash(null));
  }, []);

  useEffect(() => {
    api<{ setup_complete: boolean; ew_version?: string }>("/api/setup/status")
      .then((s) => {
        setSetupComplete(s.setup_complete);
        setVersion(s.ew_version || "");
        setPage(s.setup_complete ? "dashboard" : "setup");
      })
      .catch((e: Error) => showToast(e.message));
  }, [showToast]);

  useEffect(() => {
    if (!setupComplete) return;
    refresh();
    const ws = new WebSocket(wsUrl("/ws/status"));
    ws.onmessage = (ev) => {
      try {
        setDash(JSON.parse(ev.data) as Dashboard);
      } catch {
        /* ignore */
      }
    };
    return () => ws.close();
  }, [setupComplete, refresh]);

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

  const running = Boolean(dash?.running);
  const later = setupComplete;

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
            disabled={!later || running || busy}
            onClick={() =>
              setModal({ title: "Earthworm 시작", body: "startstop 을 백그라운드로 기동합니다.", action: "start" })
            }
          >
            시작
          </button>
          <button disabled={!later || !running || busy} onClick={() => void control("pause")}>
            일시중지
          </button>
          <button disabled={!later || !running || busy} onClick={() => void control("resume")}>
            재개
          </button>
          <button
            className="danger"
            disabled={!later || busy}
            onClick={() => setModal({ title: "전체 종료", body: "pau 를 보냅니다.", action: "stop" })}
          >
            전체중지
          </button>
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
        {NAV.map((n) => (
          <button
            key={n.id}
            className={`nav-btn ${page === n.id ? "active" : ""}`}
            disabled={!later}
            onClick={() => setPage(n.id)}
          >
            {n.label}
          </button>
        ))}
      </aside>
      <main className="main">
        {page === "setup" && (
          <SetupWizard
            toast={showToast}
            onDone={() => {
              setSetupComplete(true);
              setPage("dashboard");
              refresh();
            }}
          />
        )}
        {page === "dashboard" && <DashboardPage dash={dash} toast={showToast} refresh={refresh} />}
        {page === "foundation" && <FoundationPage toast={showToast} locked={running} />}
        {page === "modules" && <ModulesPage toast={showToast} running={running} />}
        {page === "variables" && <VariablesPage toast={showToast} />}
        {page === "files" && <FilesPage toast={showToast} />}
        {page === "logs" && <LogsPage toast={showToast} />}
        {page === "sniff" && <SniffPage toast={showToast} />}
        {page === "diagnostics" && <DiagnosticsPage toast={showToast} />}
        {page === "settings" && <SettingsPage toast={showToast} />}
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
