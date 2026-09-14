import { useEffect, useState } from "react";
import { api, type Operator } from "../api/client";
import { Field } from "../components/Confirm";

const ROLES = [
  { id: "admin", label: "관리자" },
  { id: "operator", label: "운영자" },
  { id: "viewer", label: "조회자" },
];

export function OperatorsPage({ toast }: { toast: (m: string) => void }) {
  const [rows, setRows] = useState<Operator[]>([]);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("operator");

  async function load() {
    const data = await api<{ operators: Operator[] }>("/api/operators");
    setRows(data.operators);
  }
  useEffect(() => {
    load().catch((e: Error) => toast(e.message));
  }, [toast]);

  async function create() {
    try {
      await api("/api/operators", {
        method: "POST",
        body: JSON.stringify({
          username,
          display_name: displayName || username,
          password,
          role,
        }),
      });
      setUsername("");
      setDisplayName("");
      setPassword("");
      toast("작업자를 등록했습니다");
      await load();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  async function patch(id: number, body: Record<string, unknown>) {
    try {
      await api(`/api/operators/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      await load();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  return (
    <>
      <h2>작업자</h2>
      <p className="lead">하드 삭제는 없습니다. 정지만 가능하며 마지막 관리자는 정지할 수 없습니다.</p>
      <div className="card">
        <h3>등록</h3>
        <div className="grid cols-2">
          <Field label="로그인 ID" value={username} onChange={setUsername} />
          <Field label="표시 이름" value={displayName} onChange={setDisplayName} />
          <Field label="비밀번호" value={password} onChange={setPassword} type="password" />
          <div>
            <label>역할</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button className="primary" style={{ marginTop: 10 }} onClick={() => void create()}>
          등록
        </button>
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>로그인</th>
              <th>표시 이름</th>
              <th>역할</th>
              <th>상태</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => (
              <tr key={o.id}>
                <td>{o.id}</td>
                <td>{o.username}</td>
                <td>{o.display_name}</td>
                <td>
                  <select
                    value={o.role}
                    onChange={(e) => void patch(o.id, { role: e.target.value })}
                  >
                    {ROLES.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{o.enabled ? "사용" : "정지"}</td>
                <td>
                  <button onClick={() => void patch(o.id, { enabled: !o.enabled })}>
                    {o.enabled ? "정지" : "재개"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
