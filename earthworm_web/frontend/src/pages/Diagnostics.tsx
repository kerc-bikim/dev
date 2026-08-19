import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ConfirmModal, Field } from "../components/Confirm";

export function DiagnosticsPage({ toast }: { toast: (m: string) => void }) {
  const [lock, setLock] = useState<{ path: string; exists: boolean; pid: number | null; alive: boolean } | null>(
    null
  );
  const [ipc, setIpc] = useState<{ raw: string; available: boolean } | null>(null);
  const [confirm, setConfirm] = useState(false);

  async function load() {
    const [l, i] = await Promise.all([
      api<{ path: string; exists: boolean; pid: number | null; alive: boolean }>("/api/diagnostics/lock"),
      api<{ raw: string; available: boolean }>("/api/diagnostics/ipc"),
    ]);
    setLock(l);
    setIpc(i);
  }
  useEffect(() => {
    load().catch((e: Error) => toast(e.message));
  }, [toast]);

  return (
    <>
      <h2>진단</h2>
      <p className="lead">락파일과 잔류 IPC. 자동 ipcrm 은 하지 않습니다.</p>
      <div className="grid cols-2">
        <div className="card">
          <h3>락파일</h3>
          <p>
            <code>{lock?.path}</code>
          </p>
          <p>
            {lock?.exists
              ? `있음 pid=${lock.pid} ${lock.alive ? "(살아 있음)" : "(죽은 프로세스)"}`
              : "없음"}
          </p>
          <button className="danger" disabled={!lock?.exists} onClick={() => setConfirm(true)}>
            확인 후 강제 해제
          </button>
        </div>
        <div className="card">
          <h3>IPC</h3>
          <pre className="logbox" style={{ height: 180 }}>
            {ipc?.available ? ipc.raw || "(비어 있음)" : "ipcs 없음"}
          </pre>
        </div>
      </div>
      {confirm && (
        <ConfirmModal
          title="락 강제 해제"
          body="startstop 가 살아 있으면 안 됩니다."
          onCancel={() => setConfirm(false)}
          onOk={() => {
            setConfirm(false);
            api("/api/diagnostics/lock/unlock", {
              method: "POST",
              body: JSON.stringify({ confirm: true, force: true }),
            })
              .then(() => {
                toast("락 해제");
                return load();
              })
              .catch((e: Error) => toast(e.message));
          }}
        />
      )}
    </>
  );
}

export function SettingsPage({ toast }: { toast: (m: string) => void }) {
  const [status, setStatus] = useState("2");
  const [sniff, setSniff] = useState("2");
  const [ret, setRet] = useState("14");

  useEffect(() => {
    api<{ status_interval_sec: number; sniff_session_limit: number; log_retention_days: number }>(
      "/api/settings"
    )
      .then((d) => {
        setStatus(String(d.status_interval_sec));
        setSniff(String(d.sniff_session_limit));
        setRet(String(d.log_retention_days));
      })
      .catch((e: Error) => toast(e.message));
  }, [toast]);

  async function save() {
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          status_interval_sec: Number(status),
          sniff_session_limit: Number(sniff),
          log_retention_days: Number(ret),
        }),
      });
      toast("설정 저장");
    } catch (e) {
      toast((e as Error).message);
    }
  }

  return (
    <>
      <h2>설정</h2>
      <div className="card grid cols-2">
        <Field label="상태 주기(초)" value={status} onChange={setStatus} type="number" />
        <Field label="sniff 세션 상한" value={sniff} onChange={setSniff} type="number" />
        <Field label="로그 보관 일수" value={ret} onChange={setRet} type="number" />
      </div>
      <button className="primary" onClick={() => void save()}>
        저장
      </button>
    </>
  );
}
