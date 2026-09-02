import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  apiBlob,
  apiGet,
  readError,
  type AuditList,
  type OpsStatus,
  type RestoreResult,
} from "../api";

type Tab = "audit" | "backup";

export function OpsPage({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("audit");
  const [status, setStatus] = useState<OpsStatus | null>(null);
  const [audit, setAudit] = useState<AuditList | null>(null);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoreNote, setRestoreNote] = useState<string | null>(null);

  const refreshStatus = useCallback(() => {
    apiGet<OpsStatus>("/api/ops/status")
      .then(setStatus)
      .catch((err: Error) => setError(err.message));
  }, []);

  const refreshAudit = useCallback(() => {
    const params = new URLSearchParams({ limit: "50" });
    if (actor.trim()) params.set("actor", actor.trim());
    if (action.trim()) params.set("action", action.trim());
    apiGet<AuditList>(`/api/ops/audit?${params.toString()}`)
      .then(setAudit)
      .catch((err: Error) => setError(err.message));
  }, [actor, action]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (tab === "audit") refreshAudit();
  }, [tab, refreshAudit]);

  async function onDownload() {
    setBusy(true);
    setError(null);
    try {
      const blob = await apiBlob("/api/ops/backup");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "pdcc-stationxml-backup.zip";
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onRestore(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("snapshot") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      setError("복원할 ZIP 또는 StationXML 파일을 고르세요");
      return;
    }
    setBusy(true);
    setError(null);
    setRestoreNote(null);
    try {
      const xml = file.name.toLowerCase().endsWith(".xml");
      const response = await fetch("/api/ops/restore", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": xml ? "application/xml" : "application/zip" },
        body: await file.arrayBuffer(),
      });
      if (!response.ok) throw new Error(await readError(response));
      const body = (await response.json()) as RestoreResult;
      setRestoreNote(
        `복원 ${body.count}건 (생성 ${body.created.length}, 교체 ${body.replaced.length})`
      );
      refreshAudit();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workbench">
      <div className="editor-top">
        <button type="button" onClick={onBack}>
          프로젝트 목록
        </button>
        <h2>운영</h2>
      </div>
      <p className="hint">
        StationXML 원문 스냅샷과 감사 로그입니다. SEED/RESP 내보내기와는 별개입니다.
      </p>
      {status ? (
        <p className="hint">
          환경 <code>{status.env}</code>
          {status.production ? " · 프로덕션" : " · 개발"}
          {status.allow_stub_login ? " · 스텁 로그인 허용" : " · 스텁 로그인 꺼짐"}
          {status.app_secret_is_default ? " · APP_SECRET 기본값" : ""}
          {` · 쿠키 Secure ${status.session_cookie_secure ? "켜짐" : "꺼짐"}`}
          {` · 감사 보관 ${status.audit_retention_days}일`}
        </p>
      ) : null}
      <div className="tabs">
        <button
          type="button"
          className={tab === "audit" ? "tab active" : "tab"}
          onClick={() => setTab("audit")}
        >
          감사 로그
        </button>
        <button
          type="button"
          className={tab === "backup" ? "tab active" : "tab"}
          onClick={() => setTab("backup")}
        >
          백업 · 복원
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {tab === "audit" ? (
        <div className="ops-panel">
          <form
            className="project-create"
            onSubmit={(event) => {
              event.preventDefault();
              refreshAudit();
            }}
          >
            <label>
              사용자
              <input value={actor} onChange={(e) => setActor(e.target.value)} />
            </label>
            <label>
              동작
              <input
                value={action}
                onChange={(e) => setAction(e.target.value)}
                placeholder="create, nrl, backup…"
              />
            </label>
            <button type="submit" disabled={busy}>
              조회
            </button>
          </form>
          <p className="hint">
            {audit
              ? `${audit.total}건 · 보관 ${audit.retention_days}일. curl 예: GET /api/ops/audit`
              : "불러오는 중…"}
          </p>
          <table className="confirm-table">
            <thead>
              <tr>
                <th>시각</th>
                <th>사용자</th>
                <th>동작</th>
                <th>대상</th>
                <th>요약</th>
              </tr>
            </thead>
            <tbody>
              {(audit?.items || []).map((row) => (
                <tr key={row.id}>
                  <td>{row.created_at?.replace("T", " ").slice(0, 19) || "—"}</td>
                  <td>{row.actor}</td>
                  <td>{row.action}</td>
                  <td>
                    {row.project_id ? `#${row.project_id} ` : ""}
                    {row.target}
                  </td>
                  <td>{row.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {audit && audit.items.length === 0 ? (
            <p className="hint">기록된 감사가 없습니다.</p>
          ) : null}
        </div>
      ) : (
        <div className="ops-panel">
          <div className="nrl-card">
            <h3>스냅샷 내려받기</h3>
            <p className="hint">
              모든 프로젝트 StationXML과 manifest.json 이 들어 있는 ZIP입니다. DB 전체 덤프는{" "}
              <code>pdcc_web/infra/runbook.md</code> 를 보세요.
            </p>
            <button type="button" className="primary" onClick={onDownload} disabled={busy}>
              ZIP 내려받기
            </button>
          </div>
          <form className="nrl-card" onSubmit={onRestore}>
            <h3>스냅샷 복원</h3>
            <p className="hint">
              ZIP 또는 단일 StationXML을 새 프로젝트로 가져옵니다. 기존 행을 덮어쓰려면 관리자가{" "}
              <code>POST /api/ops/restore?replace=true</code> 를 씁니다.
            </p>
            <label>
              파일
              <input name="snapshot" type="file" accept=".zip,.xml,application/zip,application/xml" />
            </label>
            <button type="submit" className="primary" disabled={busy}>
              복원
            </button>
            {restoreNote ? <p className="ok">{restoreNote}</p> : null}
          </form>
        </div>
      )}
    </div>
  );
}
