import { FormEvent, useCallback, useEffect, useState } from "react";
import { readError, type Health, type Me, type NrlStatus } from "./api";
import { AdminPage } from "./editor/AdminPage";
import { EditorPage } from "./editor/EditorPage";
import { ProjectHome } from "./editor/ProjectHome";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apiReachable, setApiReachable] = useState(false);
  const [nrlStatus, setNrlStatus] = useState<NrlStatus | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [username, setUsername] = useState("stub");
  const [password, setPassword] = useState("stub");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [adminView, setAdminView] = useState(
    () => window.location.pathname.startsWith("/admin")
  );

  const refreshHealth = useCallback(() => {
    fetch("/api/health", { credentials: "include" })
      .then(async (response) => {
        const body = (await response.json()) as Health;
        setHealth(body);
        setApiReachable(true);
      })
      .catch(() => {
        setHealth(null);
        setApiReachable(false);
      });
  }, []);

  const refreshMe = useCallback(() => {
    fetch("/api/me", { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) {
          setMe(null);
          return;
        }
        setMe((await response.json()) as Me);
      })
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    refreshHealth();
    refreshMe();
    const id = window.setInterval(refreshHealth, 5000);
    return () => window.clearInterval(id);
  }, [refreshHealth, refreshMe]);

  useEffect(() => {
    function onPop() {
      setAdminView(window.location.pathname.startsWith("/admin"));
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    if (!me) {
      setNrlStatus(null);
      return;
    }
    const load = () => {
      fetch("/api/nrl/status", { credentials: "include" })
        .then(async (response) => {
          if (!response.ok) return;
          setNrlStatus((await response.json()) as NrlStatus);
        })
        .catch(() => undefined);
    };
    load();
    const id = window.setInterval(load, 10000);
    return () => window.clearInterval(id);
  }, [me]);

  async function onLogin(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        setMessage(await readError(response));
        setMe(null);
        return;
      }
      setMe((await response.json()) as Me);
      setPassword("");
    } catch {
      setMessage("API에 연결할 수 없습니다");
    } finally {
      setBusy(false);
      refreshHealth();
    }
  }

  async function onLogout() {
    setBusy(true);
    try {
      await fetch("/api/logout", { method: "POST", credentials: "include" });
      setMe(null);
      setProjectId(null);
      if (window.location.pathname.startsWith("/admin")) {
        window.history.replaceState({}, "", "/");
        setAdminView(false);
      }
    } finally {
      setBusy(false);
    }
  }

  const apiLabel = !apiReachable ? "API 오류" : health?.ok ? "API OK" : "API 저하";
  const showAdmin = Boolean(me && adminView && me.role === "admin");

  function openAdmin() {
    window.history.pushState({}, "", "/admin");
    setAdminView(true);
    setProjectId(null);
  }

  function openHome() {
    window.history.pushState({}, "", "/");
    setAdminView(false);
    setProjectId(null);
  }

  useEffect(() => {
    if (me && adminView && me.role !== "admin") {
      window.history.replaceState({}, "", "/");
      setAdminView(false);
    }
  }, [me, adminView]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>PDCC Web</h1>
          <small>NRL 위저드 · StationXML 편집기</small>
        </div>
        {me ? (
          <div className="controls">
            <span className="badge ok">
              {me.username} · {me.role === "viewer" ? "조회자" : me.role === "admin" ? "관리자" : "편집자"}
            </span>
            {me.role === "admin" ? (
              <button type="button" onClick={showAdmin ? openHome : openAdmin}>
                {showAdmin ? "홈" : "관리"}
              </button>
            ) : null}
            <button type="button" onClick={onLogout} disabled={busy}>
              로그아웃
            </button>
          </div>
        ) : null}
      </header>

      {me ? (
        <main className="main">
          {showAdmin ? (
            <AdminPage onHome={openHome} />
          ) : projectId ? (
            <EditorPage projectId={projectId} onBack={() => setProjectId(null)} />
          ) : (
            <ProjectHome me={me} onOpen={(project) => setProjectId(project.id)} />
          )}
        </main>
      ) : (
        <main className="panel">
          <h2>로그인</h2>
          <p className="hint">
            스텁 계정은 <code>stub</code> / <code>stub</code> 와{" "}
            <code>stub2</code> / <code>stub2</code> 입니다.{" "}
            <code>admin</code> / <code>admin</code> 은{" "}
            <code>DEV_BOOTSTRAP_ADMIN=true</code> 일 때만 됩니다.
          </p>
          <form onSubmit={onLogin} className="login">
            <label>
              아이디
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
            </label>
            <label>
              비밀번호
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" className="primary" disabled={busy}>
              로그인
            </button>
          </form>
          {message ? <p className="error">{message}</p> : null}
        </main>
      )}

      <footer className="status-bar">
        <span className={apiReachable ? "ok" : "bad"}>{apiLabel}</span>
        <span className={health?.db ? "ok" : "muted"}>DB {health?.db ? "OK" : "—"}</span>
        <span className={health?.redis ? "ok" : "muted"}>
          Redis {health?.redis ? "OK" : "—"}
        </span>
        {me && nrlStatus ? (
          <span
            className={
              nrlStatus.source === "online" ? "ok" : nrlStatus.source === "cache" ? "warn" : "bad"
            }
          >
            NRL {nrlStatus.badge || nrlStatus.mode}
          </span>
        ) : null}
      </footer>
    </div>
  );
}
