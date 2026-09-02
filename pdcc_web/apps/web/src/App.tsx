import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiGet, readError, type Health, type Me } from "./api";
import { EditorPage } from "./editor/EditorPage";
import { ProjectHome } from "./editor/ProjectHome";
import { OpsPage } from "./ops/OpsPage";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apiReachable, setApiReachable] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [username, setUsername] = useState("stub");
  const [password, setPassword] = useState("stub");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [opsOpen, setOpsOpen] = useState(false);
  const [bootstrapAvailable, setBootstrapAvailable] = useState(false);
  const [bootstrapUser, setBootstrapUser] = useState("");
  const [bootstrapPass, setBootstrapPass] = useState("");

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

  const refreshBootstrap = useCallback(() => {
    apiGet<{ available: boolean }>("/api/ops/bootstrap")
      .then((body) => setBootstrapAvailable(body.available))
      .catch(() => setBootstrapAvailable(false));
  }, []);

  useEffect(() => {
    refreshHealth();
    refreshMe();
    refreshBootstrap();
    const id = window.setInterval(refreshHealth, 5000);
    return () => window.clearInterval(id);
  }, [refreshHealth, refreshMe, refreshBootstrap]);

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

  async function onBootstrap(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/ops/bootstrap", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: bootstrapUser, password: bootstrapPass }),
      });
      if (!response.ok) {
        setMessage(await readError(response));
        return;
      }
      setUsername(bootstrapUser);
      setPassword(bootstrapPass);
      setBootstrapAvailable(false);
      setMessage("최초 관리자를 만들었습니다. 로그인하세요.");
      setBootstrapPass("");
    } catch {
      setMessage("API에 연결할 수 없습니다");
    } finally {
      setBusy(false);
      refreshBootstrap();
    }
  }

  async function onLogout() {
    setBusy(true);
    try {
      await fetch("/api/logout", { method: "POST", credentials: "include" });
      setMe(null);
      setProjectId(null);
      setOpsOpen(false);
      refreshBootstrap();
    } finally {
      setBusy(false);
    }
  }

  const apiLabel = !apiReachable ? "API 오류" : health?.ok ? "API OK" : "API 저하";

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
              {me.username} · {me.role}
            </span>
            <button type="button" onClick={() => setOpsOpen(true)}>
              운영
            </button>
            <button type="button" onClick={onLogout} disabled={busy}>
              로그아웃
            </button>
          </div>
        ) : null}
      </header>

      {me ? (
        <main className="main">
          {opsOpen ? (
            <OpsPage onBack={() => setOpsOpen(false)} />
          ) : projectId ? (
            <EditorPage projectId={projectId} onBack={() => setProjectId(null)} />
          ) : (
            <ProjectHome onOpen={(project) => setProjectId(project.id)} />
          )}
        </main>
      ) : (
        <main className="panel">
          <h2>로그인</h2>
          <p className="hint">
            개발 스텁은 <code>stub</code> / <code>stub</code> 와{" "}
            <code>stub2</code> / <code>stub2</code> 입니다. 프로덕션에서는 스텁이 꺼집니다.{" "}
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
          {bootstrapAvailable ? (
            <form onSubmit={onBootstrap} className="login">
              <h3>최초 관리자</h3>
              <p className="hint">사용자가 없을 때만 한 번 만들 수 있습니다.</p>
              <label>
                아이디
                <input
                  value={bootstrapUser}
                  onChange={(e) => setBootstrapUser(e.target.value)}
                  autoComplete="off"
                />
              </label>
              <label>
                비밀번호 (8자 이상)
                <input
                  type="password"
                  value={bootstrapPass}
                  onChange={(e) => setBootstrapPass(e.target.value)}
                  autoComplete="new-password"
                />
              </label>
              <button type="submit" disabled={busy}>
                관리자 만들기
              </button>
            </form>
          ) : null}
          {message ? <p className={message.includes("만들었습니다") ? "ok" : "error"}>{message}</p> : null}
        </main>
      )}

      <footer className="status-bar">
        <span className={apiReachable ? "ok" : "bad"}>{apiLabel}</span>
        <span className={health?.db ? "ok" : "muted"}>DB {health?.db ? "OK" : "—"}</span>
        <span className={health?.redis ? "ok" : "muted"}>
          Redis {health?.redis ? "OK" : "—"}
        </span>
      </footer>
    </div>
  );
}
