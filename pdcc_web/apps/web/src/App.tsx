import { FormEvent, useCallback, useEffect, useState } from "react";
import { readError, type Health, type Me } from "./api";
import { NrlWorkbench } from "./nrl/NrlWorkbench";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [apiReachable, setApiReachable] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [username, setUsername] = useState("stub");
  const [password, setPassword] = useState("stub");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
            <button type="button" onClick={onLogout} disabled={busy}>
              로그아웃
            </button>
          </div>
        ) : null}
      </header>

      {me ? (
        <main className="main">
          <NrlWorkbench />
        </main>
      ) : (
        <main className="panel">
          <h2>로그인</h2>
          <p className="hint">
            스텁 계정은 <code>stub</code> / <code>stub</code> 입니다.{" "}
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
      </footer>
    </div>
  );
}
