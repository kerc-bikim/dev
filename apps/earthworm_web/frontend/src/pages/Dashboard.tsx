import { api, type Dashboard } from "../api/client";

export function DashboardPage({
  dash,
  toast,
  refresh,
}: {
  dash: Dashboard | null;
  toast: (m: string) => void;
  refresh: () => void;
}) {
  async function act(id: string, kind: "restart" | "stop") {
    try {
      await api(`/api/control/modules/${id}/${kind}`, { method: "POST" });
      refresh();
    } catch (e) {
      toast((e as Error).message);
    }
  }
  if (!dash) return <p className="lead">상태를 불러오는 중…</p>;
  return (
    <>
      <h2>대시보드</h2>
      <p className="lead">
        프로세스 상태와 하트비트를 분리합니다.
        {dash.disk_kb != null ? ` 디스크 ${Math.round(dash.disk_kb / 1024 / 1024)} GB` : ""}
        {dash.error ? ` · ${dash.error}` : ""}
      </p>
      <div className="grid cols-4">
        {(dash.rings.length ? dash.rings : []).map((r) => (
          <div className="card" key={r.name}>
            <div className="kicker">{r.name}</div>
            <strong>{r.size_kib} KiB</strong>
            <div className="lead">key {r.key}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <h3>모듈</h3>
        <table>
          <thead>
            <tr>
              <th>이름</th>
              <th>pid</th>
              <th>process</th>
              <th>heartbeat</th>
              <th>활성</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {dash.modules.map((m) => (
              <tr key={m.id}>
                <td>{m.binary}</td>
                <td>{m.pid ?? "—"}</td>
                <td>{m.process}</td>
                <td
                  className={
                    m.heartbeat === "ok" ? "hb-ok" : m.heartbeat === "off" ? "hb-off" : "hb-bad"
                  }
                >
                  {m.heartbeat === "ok"
                    ? "정상"
                    : m.heartbeat === "off"
                      ? "꺼짐"
                      : m.heartbeat === "no-desc"
                        ? "Descriptor 없음"
                        : m.heartbeat}
                </td>
                <td>{m.enabled ? "켜짐" : "꺼짐"}</td>
                <td>
                  <button disabled={!m.pid} onClick={() => void act(m.id, "restart")}>
                    재시작
                  </button>{" "}
                  <button disabled={!m.pid || m.locked} onClick={() => void act(m.id, "stop")}>
                    중지
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
