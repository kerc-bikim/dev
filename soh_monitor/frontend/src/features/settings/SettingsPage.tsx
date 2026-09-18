import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ApiError, api, type Role } from "../../api/client";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const logs = useQuery({ queryKey: ["audit-logs"], queryFn: api.auditLogs });
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("VIEWER");
  const [error, setError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.createUser({ username, displayName, password, role }),
    onSuccess: () => {
      setUsername("");
      setDisplayName("");
      setPassword("");
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "만들지 못했다"),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <>
      <h1 className="page-title">설정</h1>
      <p className="page-subtitle">사용자와 감사 로그. 비밀번호 해시는 응답에 실리지 않는다.</p>

      <div className="card">
        <h2>사용자</h2>
        {error && <div className="notice warn">{error}</div>}
        <form className="form-grid" onSubmit={onSubmit}>
          <label className="field">
            <span>이름</span>
            <input value={username} onChange={(event) => setUsername(event.target.value)} required />
          </label>
          <label className="field">
            <span>표시 이름</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
          </label>
          <label className="field">
            <span>초기 비밀번호</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={10} required />
          </label>
          <label className="field">
            <span>역할</span>
            <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
              <option value="VIEWER">VIEWER</option>
              <option value="OPERATOR">OPERATOR</option>
              <option value="ADMIN">ADMIN</option>
            </select>
          </label>
          <button className="btn primary" type="submit" disabled={create.isPending}>
            사용자 추가
          </button>
        </form>
        <table>
          <thead>
            <tr>
              <th>사용자</th>
              <th>역할</th>
              <th>활성</th>
              <th>마지막 로그인</th>
            </tr>
          </thead>
          <tbody>
            {(users.data?.users ?? []).map((user) => (
              <tr key={user.id}>
                <td>
                  {user.displayName} <span className="muted">({user.username})</span>
                </td>
                <td>{user.role}</td>
                <td>{user.enabled ? "예" : "아니오"}</td>
                <td>{user.lastLoginAt?.replace("T", " ").slice(0, 19) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>감사 로그</h2>
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>주체</th>
              <th>동작</th>
              <th>대상</th>
            </tr>
          </thead>
          <tbody>
            {(logs.data?.logs ?? []).map((row) => (
              <tr key={row.id}>
                <td>{row.occurredAt?.replace("T", " ").slice(0, 19)}</td>
                <td>{row.actorName ?? "—"}</td>
                <td>{row.action}</td>
                <td>
                  {row.entityType} {row.entityId ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
