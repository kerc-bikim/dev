import { useState } from "react";
import {
  apiPost,
  apiPostResponse,
  parseExportError,
  type ChannelSummary,
  type ExportJob,
  type ExportLoss,
  type ExportPreview,
  type StationSummary,
} from "../api";

type Kind = "resp" | "dataless";
type Scope = "channel" | "station" | "project";

function LossTable({ rows, title }: { rows: ExportLoss[]; title: string }) {
  if (!rows.length) return null;
  return (
    <div>
      <h4>{title}</h4>
      <table className="confirm-table">
        <thead>
          <tr>
            <th>대상</th>
            <th>내용</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.nslc}-${row.field}-${index}`}>
              <td className="mono">{row.nslc}</td>
              <td>{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExportPanel({
  projectId,
  station,
  channel,
  onQueued,
}: {
  projectId: number;
  station: StationSummary | null;
  channel: ChannelSummary | null;
  onQueued?: (job: ExportJob) => void;
}) {
  const [kind, setKind] = useState<Kind>("resp");
  const [scope, setScope] = useState<Scope>("station");
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState<ExportJob | null>(null);

  const body = {
    kind,
    scope,
    station: scope === "project" ? null : station?.code ?? null,
    start_time: scope === "project" ? null : station?.start ?? null,
    nslc: scope === "channel" ? channel?.nslc ?? null : null,
  };

  async function runPreview() {
    setBusy(true);
    setError(null);
    setQueued(null);
    try {
      const data = await apiPost<ExportPreview>(`/api/projects/${projectId}/export`, {
        ...body,
        preview: true,
      });
      setPreview(data);
    } catch (err) {
      setPreview(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function enqueue(acceptLosses: boolean) {
    setBusy(true);
    setError(null);
    try {
      const response = await apiPostResponse(`/api/projects/${projectId}/export`, {
        ...body,
        accept_losses: acceptLosses,
      });
      if (!response.ok) {
        const parsed = await parseExportError(response);
        setError(parsed.message);
        if (parsed.preview) {
          setPreview({
            kind,
            channel_count: parsed.preview.channel_count || 0,
            errors: parsed.preview.errors || [],
            losses: parsed.preview.losses || [],
            drops: parsed.preview.drops || [],
            needs_confirm: Boolean(parsed.preview.needs_confirm),
            blocked: Boolean(parsed.preview.blocked),
          });
        }
        return;
      }
      const job = (await response.json()) as ExportJob;
      setQueued(job);
      setPreview(null);
      onQueued?.(job);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="nrl-card export-card">
      <h3>내보내기</h3>
      <p className="hint">
        StationXML 원문은 그대로 두고, RESP와 dataless SEED만 만듭니다. 큰 변환은 작업 큐에서
        돌아갑니다. 파형 MiniSEED는 내보내지 않습니다.
      </p>
      <div className="export-row">
        <label>
          형식
          <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            <option value="resp">RESP</option>
            <option value="dataless">Dataless SEED</option>
          </select>
        </label>
        <label>
          범위
          <select value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
            <option value="channel">선택 채널</option>
            <option value="station">선택 관측소</option>
            <option value="project">프로젝트</option>
          </select>
        </label>
      </div>
      <p className="mono">
        {scope === "channel"
          ? channel?.nslc || "채널을 고르세요"
          : scope === "station"
            ? station
              ? `${station.code} ${station.start?.slice(0, 10)}`
              : "관측소를 고르세요"
            : "프로젝트 전체"}
      </p>
      <div className="wizard-nav">
        <button type="button" onClick={() => void runPreview()} disabled={busy}>
          손실 미리보기
        </button>
        <button
          type="button"
          className="primary"
          onClick={() => void enqueue(false)}
          disabled={busy || (scope !== "project" && !station) || (scope === "channel" && !channel)}
        >
          작업 넣기
        </button>
      </div>
      {queued ? (
        <p className="hint">
          작업을 넣었습니다. 위쪽 <strong>작업</strong> 벨에서 진행과 받기를 확인하세요.
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
      {preview ? (
        <div>
          <p className="hint">
            채널 {preview.channel_count}개
            {preview.blocked ? " · SEED/RESP를 만들 수 없습니다" : ""}
            {preview.needs_confirm ? " · 잘림 확인이 필요합니다" : ""}
          </p>
          <LossTable rows={preview.errors} title="오류 (내보내기 불가)" />
          <LossTable rows={preview.losses} title="잘림·대체 (확인 후 진행)" />
          <LossTable rows={preview.drops} title="SEED에 없는 필드" />
          {preview.needs_confirm && !preview.blocked ? (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={() => void enqueue(true)}
            >
              잘림을 확인하고 작업 넣기
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
