import { useState } from "react";
import { ApiError, apiGet, apiPost, type SeedLossReport } from "../api";

const KIND_LABEL: Record<string, string> = {
  truncate: "잘림",
  drop: "제거",
};

const FIELD_LABEL: Record<string, string> = {
  comment: "코멘트",
  fir: "FIR 이름",
  identifier: "Identifier",
  equipment: "Equipment",
  extension: "확장 필드",
  waterlevel: "WaterLevel",
  vault: "Vault",
  geology: "Geology",
  dataavailability: "DataAvailability",
  externalreference: "ExternalReference",
  sourceid: "SourceID",
};

export function SeedLossDialog({
  projectId,
  onCancel,
}: {
  projectId: number;
  onCancel: () => void;
}) {
  const [report, setReport] = useState<SeedLossReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  async function loadTable() {
    setBusy(true);
    setError(null);
    try {
      const data = await apiGet<SeedLossReport>(`/api/projects/${projectId}/export/seed-loss`);
      setReport(data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmExport() {
    if (!report) return;
    setBusy(true);
    setError(null);
    try {
      await apiPost(`/api/projects/${projectId}/export/seed?loss_ack=${encodeURIComponent(report.ack)}`);
      setDone("dataless SEED 작업을 넣었습니다");
    } catch (err) {
      if (err instanceof ApiError && err.status === 501) {
        setDone("손실 목록을 확인했습니다. dataless SEED 변환기는 이 배포에 아직 없습니다");
        return;
      }
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="nrl-card wizard" id="seed-loss-dialog" role="dialog" aria-label="SEED 변환 손실">
      <h3>SEED 변환 손실</h3>
      <p className="hint">
        이 표를 본 뒤에만 dataless SEED를 만들 수 있습니다. 왕복 변환 후 XML이 바이트 단위로 같지 않을 수
        있습니다.
      </p>
      <ul className="loss-notices" id="seed-loss-notices">
        {(report?.notices ?? [
          "StationXML 확장 필드는 제거됩니다",
          "긴 설명·코멘트는 잘립니다",
          "Identifier, 일부 Equipment 상세는 매핑되지 않을 수 있습니다",
          "왕복 변환 후 XML이 바이트 단위로 같지 않을 수 있습니다",
        ]).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {report ? (
        report.rows.length === 0 ? (
          <p className="hint" id="seed-loss-empty">
            잘리거나 제거될 필드가 없습니다. 위 안내는 그대로 적용됩니다.
          </p>
        ) : (
          <div className="clone-table-wrap">
            <table className="confirm-table" id="seed-loss-table">
              <thead>
                <tr>
                  <th>종류</th>
                  <th>경로</th>
                  <th>필드</th>
                  <th>원문</th>
                  <th>SEED</th>
                  <th>안내</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row, index) => (
                  <tr key={`${row.code}-${row.path}-${index}`} data-loss-code={row.code}>
                    <td>{KIND_LABEL[row.kind] || row.kind}</td>
                    <td className="mono">{row.path}</td>
                    <td>{FIELD_LABEL[row.field] || row.field}</td>
                    <td className="loss-original">{row.original}</td>
                    <td className="mono">{row.seed_value || "—"}</td>
                    <td>{row.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}
      {report ? (
        <p className="hint" id="seed-loss-counts">
          잘림 {report.trunc_count} · 제거 {report.drop_count}
          {report.can_export_seed
            ? ""
            : ` · 오류 ${report.error_count}개 — SEED를 만들 수 없습니다`}
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
      {done ? <p className="hint" id="seed-loss-done">{done}</p> : null}
      <div className="wizard-nav">
        <button type="button" onClick={onCancel} disabled={busy}>
          닫기
        </button>
        <button type="button" id="seed-loss-open" onClick={() => loadTable()} disabled={busy || Boolean(report)}>
          손실 목록 보기
        </button>
        <button
          type="button"
          className="primary"
          id="seed-loss-ack"
          disabled={busy || !report || !report.can_export_seed || Boolean(done)}
          onClick={() => confirmExport()}
        >
          확인 후 내보내기
        </button>
      </div>
    </div>
  );
}
