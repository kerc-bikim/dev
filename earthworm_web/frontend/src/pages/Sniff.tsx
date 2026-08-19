import { useEffect, useRef, useState } from "react";
import { api, wsUrl } from "../api/client";
import { ConfirmModal } from "../components/Confirm";

type Ring = { name: string };

export function SniffPage({ toast }: { toast: (m: string) => void }) {
  const [rings, setRings] = useState<Ring[]>([]);
  const [tool, setTool] = useState("sniffwave");
  const [ring, setRing] = useState("WAVE_RING");
  const [sta, setSta] = useState("wild");
  const [comp, setComp] = useState("wild");
  const [net, setNet] = useState("wild");
  const [loc, setLoc] = useState("wild");
  const [flag, setFlag] = useState("n");
  const [session, setSession] = useState<string | null>(null);
  const [lines, setLines] = useState<string[]>(["대기 중"]);
  const [warnY, setWarnY] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    api<{ rings: Ring[] }>("/api/rings")
      .then((d) => {
        setRings(d.rings);
        if (d.rings[0]) setRing(d.rings.find((r) => r.name === "WAVE_RING")?.name || d.rings[0].name);
      })
      .catch((e: Error) => toast(e.message));
    return () => {
      wsRef.current?.close();
    };
  }, [toast]);

  async function start() {
    if (flag === "y") {
      setWarnY(true);
      return;
    }
    await begin();
  }

  async function begin() {
    setWarnY(false);
    try {
      const res = await api<{ session_id: string }>("/api/sniff/sessions", {
        method: "POST",
        body: JSON.stringify({ tool, ring, sta, comp, net, loc, flag }),
      });
      setSession(res.session_id);
      setLines([]);
      const ws = new WebSocket(wsUrl("/ws/sniff", { session: res.session_id }));
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as { type: string; text?: string };
        if (msg.type === "line" && msg.text) {
          setLines((prev) => [...prev.slice(-80), msg.text!]);
        }
      };
    } catch (e) {
      toast((e as Error).message);
    }
  }

  async function stop() {
    wsRef.current?.close();
    if (session) {
      await api(`/api/sniff/sessions/${session}`, { method: "DELETE" });
    }
    setSession(null);
  }

  return (
    <>
      <h2>링 모니터</h2>
      <p className="lead">sniffwave / sniffring stdout 을 WebSocket 으로 중계합니다. 세션 상한 2.</p>
      <div className="card grid cols-2">
        <div>
          <label>도구</label>
          <select value={tool} onChange={(e) => setTool(e.target.value)}>
            <option>sniffwave</option>
            <option>sniffring</option>
          </select>
        </div>
        <div>
          <label>링</label>
          <select value={ring} onChange={(e) => setRing(e.target.value)}>
            {rings.map((r) => (
              <option key={r.name}>{r.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label>Sta</label>
          <input value={sta} onChange={(e) => setSta(e.target.value)} />
        </div>
        <div>
          <label>Comp</label>
          <input value={comp} onChange={(e) => setComp(e.target.value)} />
        </div>
        <div>
          <label>Net</label>
          <input value={net} onChange={(e) => setNet(e.target.value)} />
        </div>
        <div>
          <label>Loc</label>
          <input value={loc} onChange={(e) => setLoc(e.target.value)} />
        </div>
        <div>
          <label>데이터 플래그</label>
          <select value={flag} onChange={(e) => setFlag(e.target.value)}>
            <option value="n">n 헤더만</option>
            <option value="s">s 통계</option>
            <option value="y">y 샘플 (폭주 주의)</option>
          </select>
        </div>
      </div>
      <div className="row">
        <button className="primary" disabled={!!session} onClick={() => void start()}>
          시작
        </button>
        <button disabled={!session} onClick={() => void stop()}>
          중지
        </button>
      </div>
      <div className="logbox">{lines.join("\n")}</div>
      {warnY && (
        <ConfirmModal
          title="샘플 덤프"
          body="y 플래그는 출력이 매우 많습니다."
          onOk={() => void begin()}
          onCancel={() => setWarnY(false)}
        />
      )}
    </>
  );
}
