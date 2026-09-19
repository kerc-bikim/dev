import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";

export function LoginPage() {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!loading && user) {
    if (user.mustChangePassword) {
      return <Navigate to="/change-password" replace />;
    }
    return <Navigate to="/overview" replace />;
  }

  const expired = Boolean((location.state as { expired?: boolean } | null)?.expired);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const next = await login(username, password);
      const from = (location.state as { from?: string } | null)?.from;
      if (next.mustChangePassword) {
        navigate("/change-password", { replace: true, state: { from: from ?? "/overview" } });
      } else {
        navigate(from && from !== "/login" ? from : "/overview", { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "로그인에 실패했다");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <form className="card login-card" onSubmit={onSubmit}>
        <h1 className="page-title">관측소 SOH 모니터링</h1>
        <p className="page-subtitle">운영 화면은 로그인 뒤에만 열린다. 기록계에는 브라우저가 직접 붙지 않는다.</p>
        {expired && (
          <div className="notice warn">세션이 만료됐다. 저장하지 않은 작업은 사라졌을 수 있다. 다시 로그인한다.</div>
        )}
        {error && <div className="notice warn">{error}</div>}
        <label className="field">
          <span>사용자 이름</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
        </label>
        <label className="field">
          <span>비밀번호</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "확인 중…" : "로그인"}
        </button>
      </form>
    </div>
  );
}
