import { useEffect, useState } from "react";
import { api } from "../api/client";

type LogMod = { module: string; files: { file: string; date: string | null; size: number }[] };

export function LogsPage({ toast }: { toast: (m: string) => void }) {
  const [mods, setMods] = useState<LogMod[]>([]);
  const [file, setFile] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [settings, setSettings] = useState({ directory: "", retention_days: 14 });

  useEffect(() => {
    Promise.all([
      api<{ modules: LogMod[] }>("/api/logs"),
      api<{ directory: string; retention_days: number }>("/api/logs/settings"),
    ])
      .then(([l, s]) => {
        setMods(l.modules);
        setSettings(s);
        const first = l.modules[0]?.files[0]?.file;
        if (first) void open(first);
      })
      .catch((e: Error) => toast(e.message));
  }, [toast]);

  async function open(name: string) {
    setFile(name);
    const data = await api<{ lines: string[] }>(
      `/api/logs/content?file=${encodeURIComponent(name)}&tail=400`
    );
    setLines(data.lines);
  }

  async function saveSettings() {
    try {
      await api("/api/logs/settings", { method: "PUT", body: JSON.stringify(settings) });
      toast("로그 설정 저장. 경로 변경은 재시작 후 유효합니다.");
    } catch (e) {
      toast((e as Error).message);
    }
  }

  return (
    <>
      <h2>로그</h2>
      <p className="lead">
        {settings.directory} · 보관 {settings.retention_days}일 · *.lock 과 EW_DATA_DIR 은 삭제하지
        않습니다.
      </p>
      <div className="card grid cols-2">
        <div>
          <label>로그 디렉터리</label>
          <input
            value={settings.directory}
            onChange={(e) => setSettings({ ...settings, directory: e.target.value })}
          />
        </div>
        <div>
          <label>보관 일수</label>
          <input
            type="number"
            value={settings.retention_days}
            onChange={(e) => setSettings({ ...settings, retention_days: Number(e.target.value) })}
          />
        </div>
      </div>
      <button onClick={() => void saveSettings()}>설정 저장</button>
      <div className="card row" style={{ marginTop: 12 }}>
        <select value={file} onChange={(e) => void open(e.target.value)}>
          {mods.flatMap((m) =>
            m.files.map((f) => (
              <option key={f.file} value={f.file}>
                {f.file}
              </option>
            ))
          )}
        </select>
      </div>
      <div className="logbox">{lines.join("\n") || "파일 없음"}</div>
    </>
  );
}
