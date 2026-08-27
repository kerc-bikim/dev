import { useEffect, useState } from "react";
import { apiDownload, apiGet, apiPost, type Job } from "../api";

const LABELS: Record<string, string> = {
  queued: "대기",
  running: "진행 중",
  succeeded: "완료",
  failed: "실패",
  cancelled: "취소",
};

function kindLabel(kind: string): string {
  if (kind === "validate") return "검증";
  if (kind === "dataless") return "SEED";
  if (kind === "resp") return "RESP";
  return kind;
}

async function saveDownload(job: Job) {
  const { filename, blob } = await apiDownload(`/api/jobs/${job.id}/download`);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || job.filename || "export.bin";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function JobBell() {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const active = jobs.some((job) => job.status === "queued" || job.status === "running");

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const data = await apiGet<{ jobs: Job[] }>("/api/jobs");
        if (!cancelled) {
          setJobs(data.jobs);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    }
    void refresh();
    const id = window.setInterval(refresh, active || open ? 1500 : 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [open, active]);

  const activeCount = jobs.filter(
    (job) => job.status === "queued" || job.status === "running"
  ).length;

  return (
    <div className="job-bell">
      <button type="button" id="job-bell-btn" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        작업{activeCount ? ` ${activeCount}` : ""}
      </button>
      {open ? (
        <div className="job-panel" role="dialog" aria-label="작업 목록">
          <h3>작업</h3>
          {error ? <p className="error">{error}</p> : null}
          {jobs.length === 0 ? <p className="hint">아직 작업이 없습니다.</p> : null}
          <ul className="job-list">
            {jobs.map((job) => (
              <li key={job.id}>
                <div>
                  <strong>
                    {kindLabel(job.kind)} · {LABELS[job.status] || job.status}
                  </strong>
                  <span className="hint">
                    {" "}
                    {job.kind === "validate" && job.result
                      ? `오류 ${job.result.error_count} · 경고 ${job.result.warning_count}`
                      : job.filename || job.message}
                  </span>
                </div>
                <progress max={100} value={job.progress} />
                <p className="hint">{job.error || job.message}</p>
                {job.downloadable ? (
                  <button
                    type="button"
                    className="primary"
                    id={`job-download-${job.id}`}
                    onClick={() => saveDownload(job).catch((err: Error) => setError(err.message))}
                  >
                    받기
                  </button>
                ) : null}
                {job.status === "failed" ? (
                  <button
                    type="button"
                    onClick={() =>
                      apiPost<Job>(`/api/jobs/${job.id}/retry`)
                        .then((next) =>
                          setJobs((prev) => prev.map((row) => (row.id === next.id ? next : row)))
                        )
                        .catch((err: Error) => setError(err.message))
                    }
                  >
                    다시 시도
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
