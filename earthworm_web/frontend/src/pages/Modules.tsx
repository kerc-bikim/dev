import { useEffect, useState } from "react";
import { api, type ModuleRow } from "../api/client";

export function ModulesPage({ toast, running }: { toast: (m: string) => void; running: boolean }) {
  const [rows, setRows] = useState<ModuleRow[]>([]);

  async function load() {
    const data = await api<{ modules: ModuleRow[] }>("/api/modules");
    setRows(data.modules);
  }
  useEffect(() => {
    load().catch((e: Error) => toast(e.message));
  }, [toast]);

  async function toggle(m: ModuleRow) {
    try {
      const res = await api<{ statmgr_restarted?: boolean }>(`/api/modules/${m.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !m.enabled }),
      });
      if (res.statmgr_restarted) toast("reconfigure: 새 모듈 기동, statmgr 이 재시작됩니다");
      await load();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  async function clone(m: ModuleRow) {
    const name = window.prompt("복제 이름", `${m.id}_b`);
    if (!name) return;
    try {
      await api(`/api/modules/${m.id}/clone`, {
        method: "POST",
        body: JSON.stringify({ new_name: name }),
      });
      toast(`${m.binary} → ${name} 복제`);
      await load();
    } catch (e) {
      toast((e as Error).message);
    }
  }

  return (
    <>
      <h2>모듈 토글</h2>
      <p className="lead">
        구성 보드가 기본 경로입니다. 이 표는 startstop Process 주석·복제 우회입니다.
        {running ? " 기동 중 on → reconfigure, off → stopmodule." : ""}
      </p>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>bin</th>
              <th>params</th>
              <th>MyModuleId</th>
              <th>.desc</th>
              <th>활성</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.id}>
                <td>
                  {m.binary}
                  {!m.binary_exists ? <span className="hb-bad"> 바이너리 없음</span> : null}
                </td>
                <td>{m.param_file ?? "—"}</td>
                <td>{m.module_id ?? "—"}</td>
                <td>{m.desc_file ?? <span className="hb-bad">없음</span>}</td>
                <td>
                  <button
                    className={`toggle ${m.enabled ? "on" : ""}`}
                    disabled={m.locked || !m.binary_exists || !m.param_file}
                    onClick={() => void toggle(m)}
                    title="활성"
                  />
                </td>
                <td>
                  <button disabled={!m.param_file} onClick={() => void clone(m)}>
                    복제
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
