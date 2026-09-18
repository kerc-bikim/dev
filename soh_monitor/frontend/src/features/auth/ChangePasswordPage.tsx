import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";

export function ChangePasswordPage() {
  const { changePassword, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirm) {
      setError("새 비밀번호 확인이 같지 않다");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changePassword(currentPassword, newPassword);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/change-password" ? from : "/overview", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "비밀번호를 바꾸지 못했다");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-shell">
      <form className="card login-card" onSubmit={onSubmit}>
        <h1 className="page-title">비밀번호 변경</h1>
        <p className="page-subtitle">
          {user?.mustChangePassword
            ? "처음 받은 비밀번호는 반드시 바꾼 뒤에 설정을 바꿀 수 있다."
            : "현재 비밀번호를 확인한 뒤 새 비밀번호를 저장한다."}
        </p>
        {error && <div className="notice warn">{error}</div>}
        <label className="field">
          <span>현재 비밀번호</span>
          <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required />
        </label>
        <label className="field">
          <span>새 비밀번호 (10자 이상)</span>
          <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} minLength={10} required />
        </label>
        <label className="field">
          <span>새 비밀번호 확인</span>
          <input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} minLength={10} required />
        </label>
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "저장 중…" : "변경"}
        </button>
      </form>
    </div>
  );
}
