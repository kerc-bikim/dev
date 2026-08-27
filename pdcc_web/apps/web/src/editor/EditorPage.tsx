import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  apiDownload,
  apiGet,
  apiPost,
  type ChannelSummary,
  type FieldDiff,
  type Job,
  type LockInfo,
  type Project,
  type StationSummary,
  type ValidationIssue,
} from "../api";
import { NrlWorkbench } from "../nrl/NrlWorkbench";
import { MergeDialog } from "./MergeDialog";
import { StationForm } from "./StationForm";
import { StationWizard } from "./StationWizard";
import { ChannelForm } from "./ChannelForm";
import { CloneTable } from "./CloneTable";
import { ValidationPanel } from "./ValidationPanel";
import { VersionPanel } from "./VersionPanel";

export function EditorPage({
  projectId,
  onBack,
}: {
  projectId: number;
  onBack: () => void;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [wizard, setWizard] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedNslc, setSelectedNslc] = useState<string | null>(null);
  const [draftPrompt, setDraftPrompt] = useState(false);
  const [mergeFields, setMergeFields] = useState<FieldDiff[] | null>(null);
  const [viewStations, setViewStations] = useState<StationSummary[] | null>(null);
  const [treeQuery, setTreeQuery] = useState("");
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [issueSource, setIssueSource] = useState("project");
  const [issueMode, setIssueMode] = useState("quick");
  const [focusField, setFocusField] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [validateJob, setValidateJob] = useState<Job | null>(null);
  const [canSeed, setCanSeed] = useState(false);
  const [xmlName, setXmlName] = useState<string | null>(null);
  const issueModeRef = useRef(issueMode);
  issueModeRef.current = issueMode;

  const loadIssues = useCallback(async () => {
    const mode = issueModeRef.current === "full" ? "full" : "quick";
    const data = await apiGet<ValidateResult>(
      `/api/projects/${projectId}/issues?mode=${mode}`
    );
    setIssues(data.issues);
    setIssueSource(data.source);
    setIssueMode(data.mode);
    if (mode === "full") {
      setCanSeed(data.can_export_seed);
      setXmlName(data.filename);
    }
  }, [projectId]);

  const refresh = useCallback(async () => {
    const data = await apiGet<Project>(`/api/projects/${projectId}`);
    setProject(data);
    setSelectedPath((prev) => prev ?? data.stations[0]?.station_path ?? null);
    setSelectedNslc((prev) => prev ?? data.stations[0]?.channels[0]?.nslc ?? null);
    if (data.draft) setDraftPrompt(true);
    await loadIssues();
    return data;
  }, [projectId, loadIssues]);

  useEffect(() => {
    refresh()
      .then(async (data) => {
        const first = data.stations[0];
        if (!first) return;
        if (data.can_edit === false) return;
        try {
          await apiPost(
            `/api/projects/${projectId}/lock?station_path=${encodeURIComponent(first.station_path)}`
          );
          await refresh();
        } catch (err) {
          setError((err as Error).message);
          await refresh();
        }
      })
      .catch((err: Error) => setError(err.message));
  }, [projectId, refresh]);

  const stations = viewStations ?? project?.stations ?? [];
  const selected: StationSummary | null =
    stations.find((row) => row.station_path === selectedPath) ?? stations[0] ?? null;
  const channel: ChannelSummary | null =
    selected?.channels.find((row) => row.nslc === selectedNslc) ?? selected?.channels[0] ?? null;
  const lock: LockInfo | undefined = selected?.lock ?? project?.lock ?? undefined;
  const viewerOnly = project?.my_role === "viewer";
  const canEdit = Boolean(project?.can_edit);
  const readOnly = !canEdit || Boolean(lock && lock.mine === false);

  useEffect(() => {
    if (!selected || readOnly) return;
    const id = window.setInterval(() => {
      apiPost("/api/locks/heartbeat", { station_path: selected.station_path }).catch(
        () => undefined
      );
    }, 30000);
    return () => window.clearInterval(id);
  }, [selected, readOnly]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return;
      if (readOnly || !project?.can_undo) return;
      event.preventDefault();
      apiPost<{ project: Project }>(`/api/projects/${projectId}/undo`)
        .then((data) => {
          setProject(data.project);
          setViewStations(null);
        })
        .catch((err: Error) => setError(err.message));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [project?.can_undo, projectId, readOnly]);

  async function openStation(sta: StationSummary) {
    setSelectedPath(sta.station_path);
    setSelectedNslc(sta.channels[0]?.nslc ?? null);
    if (!canEdit) return;
    try {
      await apiPost(
        `/api/projects/${projectId}/lock?station_path=${encodeURIComponent(sta.station_path)}`
      );
      await refresh();
    } catch (err) {
      setError((err as Error).message);
      await refresh();
    }
  }

  async function afterDraft() {
    const data = await apiGet<{
      draft: { stations: StationSummary[] } | null;
    }>(`/api/projects/${projectId}/draft`);
    if (data.draft?.stations) setViewStations(data.draft.stations);
    await loadIssues();
  }

  function jumpToIssue(issue: ValidationIssue) {
    if (issue.station && issue.start && project) {
      const path = project.stations.find(
        (row) => row.code === issue.station && row.start === issue.start
      )?.station_path;
      const fallback = stations.find((row) => row.code === issue.station)?.station_path;
      if (path || fallback) setSelectedPath(path ?? fallback ?? null);
    }
    if (issue.nslc) setSelectedNslc(issue.nslc);
    setFocusField(issue.field);
  }

  async function runValidate() {
    setValidating(true);
    setError(null);
    try {
      const job = await apiPost<Job>(`/api/projects/${projectId}/validate`);
      setValidateJob(job);
    } catch (err) {
      setError((err as Error).message);
      setValidating(false);
    }
  }

  useEffect(() => {
    if (!validateJob) return;
    if (validateJob.status === "succeeded") {
      const data = validateJob.result;
      if (data) {
        setIssues(data.issues);
        setIssueSource(data.source);
        setIssueMode(data.mode);
        setCanSeed(data.can_export_seed);
        setXmlName(data.filename);
      }
      setValidating(false);
      return;
    }
    if (validateJob.status === "failed" || validateJob.status === "cancelled") {
      setError(validateJob.error || validateJob.message);
      setValidating(false);
      return;
    }
    const id = window.setInterval(() => {
      apiGet<Job>(`/api/jobs/${validateJob.id}`)
        .then((next) => setValidateJob(next))
        .catch((err: Error) => setError(err.message));
    }, 1200);
    return () => window.clearInterval(id);
  }, [validateJob]);

  async function downloadXml() {
    setError(null);
    try {
      const { filename, blob } = await apiDownload(
        `/api/projects/${projectId}/xml?source=draft`
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setXmlName(filename);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function downloadOriginal() {
    setError(null);
    try {
      const { filename, blob } = await apiDownload(`/api/projects/${projectId}/original`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function exportSeed() {
    setError(null);
    try {
      await apiPost(`/api/projects/${projectId}/export/seed`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function resumeDraft() {
    const data = await apiGet<{
      draft: { stations: StationSummary[]; conflict: boolean } | null;
    }>(`/api/projects/${projectId}/draft`);
    if (data.draft?.stations) setViewStations(data.draft.stations);
    setDraftPrompt(false);
    await loadIssues();
  }

  async function discardDraft() {
    await apiPost(`/api/projects/${projectId}/draft/discard`);
    setViewStations(null);
    setDraftPrompt(false);
    await refresh();
  }

  async function commitDraft() {
    setError(null);
    try {
      const data = await apiPost<{ project: Project }>(`/api/projects/${projectId}/draft/commit`);
      setProject(data.project);
      setViewStations(null);
      setMergeFields(null);
      await loadIssues();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const detail = (err.payload as { detail?: { fields?: FieldDiff[] } }).detail;
        setMergeFields(detail?.fields ?? []);
        return;
      }
      setError((err as Error).message);
    }
  }

  if (!project) {
    return (
      <div className="workbench">
        {error ? <p className="error">{error}</p> : <p className="hint">불러오는 중…</p>}
      </div>
    );
  }

  return (
    <div className="workbench">
      <div className="editor-top">
        <button type="button" onClick={onBack}>
          프로젝트 목록
        </button>
        <h2>
          {project.name} <small>{project.network_code}</small>
        </h2>
        {viewerOnly ? (
          <span className="badge warn" id="viewer-readonly-badge">
            조회자 · 읽기 전용
          </span>
        ) : null}
        <button type="button" className="primary" disabled={readOnly} onClick={() => setWizard(true)}>
          관측소 위저드
        </button>
        <button
          type="button"
          id="clone-open-btn"
          disabled={!selected || readOnly}
          onClick={() => setCloneOpen(true)}
        >
          관측소 복제
        </button>
        <button
          type="button"
          disabled={!project.can_undo || readOnly}
          onClick={() =>
            apiPost<{ project: Project }>(`/api/projects/${projectId}/undo`)
              .then((data) => {
                setProject(data.project);
                setViewStations(null);
              })
              .catch((err: Error) => setError(err.message))
          }
        >
          실행 취소
        </button>
        <button type="button" disabled={readOnly} onClick={commitDraft}>
          초안 저장
        </button>
        <button type="button" id="validate-btn" onClick={() => runValidate()}>
          {validating ? "검증 중…" : "검증"}
        </button>
        <button type="button" onClick={() => downloadXml()}>
          StationXML
        </button>
        {project.has_original ? (
          <button type="button" id="original-file-btn" onClick={() => downloadOriginal()}>
            {project.original_kind === "dataless" ? "원본 SEED" : "원본 파일"}
          </button>
        ) : null}
        <button
          type="button"
          id="export-seed-btn"
          disabled={!canSeed || readOnly}
          title={
            readOnly
              ? "조회자는 StationXML만 받을 수 있습니다"
              : canSeed
                ? "dataless SEED"
                : "오류가 있으면 SEED를 만들 수 없습니다. 먼저 검증하세요."
          }
          onClick={() => exportSeed()}
        >
          dataless SEED
        </button>
      </div>
      {lock && !viewerOnly ? (
        <p className={lock.mine ? "lock-banner mine" : "lock-banner"}>
          {lock.mine
            ? `${lock.username} 님이 수정 중 (이 세션)`
            : `${lock.username} 님이 수정 중 · 읽기 전용`}
        </p>
      ) : null}
      {draftPrompt ? (
        <p className="lock-banner">
          저장하지 않은 초안이 있습니다.{" "}
          <button type="button" className="primary" onClick={() => resumeDraft().catch((err: Error) => setError(err.message))}>
            초안 이어가기
          </button>{" "}
          <button type="button" onClick={() => discardDraft().catch((err: Error) => setError(err.message))}>
            마지막 버전으로
          </button>
        </p>
      ) : null}
      {validateJob && (validateJob.status === "queued" || validateJob.status === "running") ? (
        <p className="lock-banner" id="validate-progress">
          공식 검증 {validateJob.progress}% · 이전 결과를 유지합니다. 편집은 계속할 수 있습니다.
          <progress max={100} value={validateJob.progress} />
        </p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
      {wizard ? (
        <StationWizard
          project={project}
          onCancel={() => setWizard(false)}
          onDone={(next) => {
            setWizard(false);
            setProject(next);
            setSelectedPath(next.stations[0]?.station_path ?? null);
            setSelectedNslc(next.stations[0]?.channels[0]?.nslc ?? null);
          }}
        />
      ) : null}
      {cloneOpen && selected ? (
        <CloneTable
          project={project}
          source={selected}
          onCancel={() => setCloneOpen(false)}
          onDone={(next) => {
            setCloneOpen(false);
            setProject(next);
            setViewStations(null);
            const created = next.stations.find((row) => row.code !== selected.code);
            setSelectedPath(created?.station_path ?? next.stations[0]?.station_path ?? null);
            setSelectedNslc(created?.channels[0]?.nslc ?? next.stations[0]?.channels[0]?.nslc ?? null);
          }}
        />
      ) : null}
      {mergeFields ? (
        <MergeDialog
          projectId={projectId}
          fields={mergeFields}
          onCancel={() => setMergeFields(null)}
          onDone={() => {
            setMergeFields(null);
            refresh().catch((err: Error) => setError(err.message));
          }}
        />
      ) : null}
      <div className="editor-layout">
        <aside className="nrl-card tree">
          <h3>트리</h3>
          <p>{project.network_code}</p>
          <label>
            검색
            <input
              value={treeQuery}
              onChange={(e) => setTreeQuery(e.target.value)}
              placeholder="관측소·채널"
            />
          </label>
          {stations
            .filter((sta) => {
              const q = treeQuery.trim().toUpperCase();
              if (!q) return true;
              if (sta.code.toUpperCase().includes(q) || (sta.site_name || "").toUpperCase().includes(q)) {
                return true;
              }
              return sta.channels.some((ch) => ch.nslc.toUpperCase().includes(q) || ch.code.toUpperCase().includes(q));
            })
            .map((sta) => (
            <div key={sta.station_path}>
              <button
                type="button"
                className={selected?.station_path === sta.station_path ? "tree-node active" : "tree-node"}
                onClick={() => openStation(sta)}
              >
                {sta.code} {sta.start?.slice(0, 10)} {sta.end ? "" : "~ 현재"}
                {sta.lock?.mine === false ? " · 잠금" : ""}
              </button>
              <ul>
                {sta.channels
                  .filter((ch) => {
                    const q = treeQuery.trim().toUpperCase();
                    if (!q) return true;
                    return (
                      sta.code.toUpperCase().includes(q) ||
                      ch.nslc.toUpperCase().includes(q) ||
                      ch.code.toUpperCase().includes(q)
                    );
                  })
                  .map((ch) => (
                  <li key={ch.nslc}>
                    <button
                      type="button"
                      className={channel?.nslc === ch.nslc ? "tree-node active" : "tree-node"}
                      onClick={() => {
                        setSelectedPath(sta.station_path);
                        setSelectedNslc(ch.nslc);
                      }}
                    >
                      {ch.nslc} {ch.has_response ? "NRL" : "응답 없음"} · az {ch.azimuth} / dip{" "}
                      {ch.dip}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {stations.length === 0 ? <p className="hint">위저드로 관측소를 만드세요.</p> : null}
        </aside>
        <div>
          {selected ? (
            <StationForm
              key={selected.station_path}
              projectId={projectId}
              station={selected}
              disabled={readOnly}
              focusField={focusField}
              onDrafted={() => afterDraft().catch((err: Error) => setError(err.message))}
            />
          ) : null}
          {selected && channel ? (
            <ChannelForm
              key={channel.nslc}
              projectId={projectId}
              station={selected.code}
              start={selected.start}
              channel={channel}
              disabled={readOnly}
              focusField={focusField}
              onDrafted={() => afterDraft().catch((err: Error) => setError(err.message))}
            />
          ) : null}
          <ValidationPanel
            issues={issues}
            source={issueSource}
            mode={issueMode}
            validating={validating}
            progress={validateJob?.status === "queued" || validateJob?.status === "running" ? validateJob.progress : null}
            filename={xmlName}
            onJump={jumpToIssue}
          />
          <NrlWorkbench
            disabled={readOnly}
            apply={
              selected && channel
                ? {
                    projectId: project.id,
                    station: selected.code,
                    start: selected.start,
                    channels: selected.channels,
                    selectedNslc: channel.nslc,
                  }
                : null
            }
            onApplied={() => refresh().catch((err: Error) => setError(err.message))}
          />
          <VersionPanel
            projectId={projectId}
            disabled={readOnly}
            onRestored={() => refresh().catch((err: Error) => setError(err.message))}
          />
        </div>
      </div>
      {xmlName ? <p className="hint">마지막 StationXML 파일명: {xmlName}</p> : null}
    </div>
  );
}
