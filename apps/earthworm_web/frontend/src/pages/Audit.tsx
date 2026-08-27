import { useEffect, useState } from "react";
import { api, type AuditEvent } from "../api/client";
import { Field } from "../components/Confirm";

const RESULT_LABEL: Record<string, string> = { ok: "성공", error: "실패", denied: "거부" };

export function AuditPage({ toast }: { toast: (m: string) => void }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [result, setResult] = useState("");

  async function load() {
    const q = new URLSearchParams();
    if (actor) q.set("actor", actor);
    if (action) q.set("action", action);
    if (result) q.set("result", result);
    const data = await api<{ events: AuditEvent[]; total: number }>(`/api/audit?${q.toString()}`);
    setEvents(data.events);
    setTotal(data.total);
  }
  useEffect(() => {
    load().catch((e: Error) => toast(e.message));
  }, [toast]);

  return (
    <>
      <h2>이력</h2>
      <p className="lead">
        웹 작업 이력입니다. 모듈 로그(<code>*_YYYYMMDD.log</code>)와 다릅니다. 줄을 지우거나 고칠 수
        없습니다. 총 {total}건.
      </p>
      <div className="card grid cols-4">
        <Field label="작업자" value={actor} onChange={setActor} />
        <Field label="동작" value={action} onChange={setAction} />
        <div>
          <label>결과</label>
          <select value={result} onChange={(e) => setResult(e.target.value)}>
            <option value="">전체</option>
            <option value="ok">성공</option>
            <option value="error">실패</option>
            <option value="denied">거부</option>
          </select>
        </div>
        <div style={{ alignSelf: "end" }}>
          <button className="primary" onClick={() => void load()}>
            필터
          </button>
        </div>
      </div>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>작업자</th>
              <th>동작</th>
              <th>대상</th>
              <th>결과</th>
              <th>백업</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td>{e.at?.replace("T", " ").slice(0, 19)}</td>
                <td>{e.actor_display_name}</td>
                <td>{e.action}</td>
                <td>{e.target ?? "—"}</td>
                <td className={e.result === "ok" ? "hb-ok" : "hb-bad"}>
                  {RESULT_LABEL[e.result] || e.result}
                </td>
                <td>{e.backup_dir ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
