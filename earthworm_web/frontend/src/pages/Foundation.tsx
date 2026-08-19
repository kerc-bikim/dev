import { useEffect, useState } from "react";
import { api, type RingRow } from "../api/client";
import { Field } from "../components/Confirm";

export function FoundationPage({
  toast,
  locked,
}: {
  toast: (m: string) => void;
  locked: boolean;
}) {
  const [home, setHome] = useState("");
  const [run, setRun] = useState("");
  const [log, setLog] = useState("");
  const [rings, setRings] = useState<RingRow[]>([]);

  useEffect(() => {
    Promise.all([
      api<Record<string, string>>("/api/environment"),
      api<{ rings: RingRow[] }>("/api/setup/import-existing", { method: "POST" }),
    ])
      .then(([env, imp]) => {
        setHome(env.EW_HOME);
        setRun(env.EW_RUN_DIR);
        setLog(env.EW_LOG);
        setRings(imp.rings);
      })
      .catch((e: Error) => toast(e.message));
  }, [toast]);

  async function save() {
    try {
      await api("/api/setup/directories", {
        method: "PUT",
        body: JSON.stringify({
          EW_HOME: home,
          EW_VERSION: (await api<Record<string, string>>("/api/environment")).EW_VERSION,
          EW_RUN_DIR: run,
        }),
      });
      await api("/api/setup/rings", { method: "PUT", body: JSON.stringify({ rings }) });
      toast("기반 설정 저장. 링 변경은 전체 재시작 후 유효합니다.");
    } catch (e) {
      toast((e as Error).message);
    }
  }

  return (
    <>
      <h2>기반 설정</h2>
      <p className="lead">
        {locked
          ? "startstop 이 실행 중이면 링 크기·순서는 잠깁니다. 종료 후 수정하세요."
          : "초기 마법사와 같은 폼입니다."}
      </p>
      <div className="card">
        <h3>디렉터리</h3>
        <div className="grid cols-2">
          <Field label="EW_HOME" value={home} onChange={setHome} disabled={locked} />
          <Field label="EW_RUN_DIR" value={run} onChange={setRun} disabled={locked} />
          <Field label="EW_LOG" value={log} onChange={setLog} disabled={locked} />
        </div>
      </div>
      <div className="card">
        <h3>링</h3>
        <table>
          <thead>
            <tr>
              <th>이름</th>
              <th>키</th>
              <th>KiB</th>
              <th>startstop</th>
            </tr>
          </thead>
          <tbody>
            {rings.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>{r.key}</td>
                <td>{r.size}</td>
                <td>{r.in_startstop ? "예" : "아니오"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="primary" disabled={locked} onClick={() => void save()}>
          저장 (전체 재시작 필요)
        </button>
      </div>
    </>
  );
}
