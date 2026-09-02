import { useEffect, useState } from "react";
import { apiDownload, apiGet, apiPost, type ExportJob } from "../api";

const LABELS: Record<string, string> = {
  queued: "대기",
  running: "변환 중",
  completed: "완료",
  failed: "실패",
  cancelled: "취소",
};

function kindLabel(kind: string): string {
  return kind === "dataless" ? "SEED" : "RESP";
}

export function JobBell() {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<ExportJob[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const data = await apiGet<{ jobs: ExportJob[] }>("/api/jobs");
        if (!cancelled) {
          setJobs(data.jobs);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    }
    void refresh();
    const active = jobs.some((job) => job.status === "queued" || job.status === "running");
    const id = window.setInterval(refresh, active || open ? 2000 : 8000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [open, jobs.some((job) => job.status === "queued" || job.status === "running")]);

  const activeCount = jobs.filter(
    (job) => job.status === "queued" || job.status === "running"
  ).length;

  return (
    <div className="job-bell">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        작업{activeCount ? ` ${activeCount}` : ""}
      </button>
      {open ? (
        <div className="job-panel" role="dialog" aria-label="작업 목록">
          <h3>내보내기 작업</h3>
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
                    {job.station || "프로젝트"}
                    {job.nslc ? ` ${job.nslc}` : ""}
                  </span>
                </div>
                <progress max={100} value={job.progress} />
                <p className="hint">{job.error || job.message}</p>
                {job.downloadable ? (
                  <button
                    type="button"
                    className="primary"
                    onClick={() =>
                      apiDownload(`/api/jobs/${job.id}/download`, job.filename || "export.bin").catch(
                        (err: Error) => setError(err.message)
                      )
                    }
                  >
                    받기
                  </button>
                ) : null}
                {job.status === "failed" ? (
                  <button
                    type="button"
                    onClick={() =>
                      apiPost<ExportJob>(`/api/jobs/${job.id}/retry`)
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
