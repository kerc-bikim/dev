import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  apiGet,
  apiPost,
  apiText,
  type ChannelSummary,
  type FieldDiff,
  type LockInfo,
  type Project,
  type StationSummary,
} from "../api";
import { NrlWorkbench } from "../nrl/NrlWorkbench";
import { MergeDialog } from "./MergeDialog";
import { StationForm } from "./StationForm";
import { StationWizard } from "./StationWizard";
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
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedNslc, setSelectedNslc] = useState<string | null>(null);
  const [xml, setXml] = useState<string | null>(null);
  const [draftPrompt, setDraftPrompt] = useState(false);
  const [mergeFields, setMergeFields] = useState<FieldDiff[] | null>(null);
  const [viewStations, setViewStations] = useState<StationSummary[] | null>(null);

  const refresh = useCallback(async () => {
    const data = await apiGet<Project>(`/api/projects/${projectId}`);
    setProject(data);
    setSelectedPath((prev) => prev ?? data.stations[0]?.station_path ?? null);
    setSelectedNslc((prev) => prev ?? data.stations[0]?.channels[0]?.nslc ?? null);
    if (data.draft) setDraftPrompt(true);
    return data;
  }, [projectId]);

  useEffect(() => {
    refresh()
      .then(async (data) => {
        const first = data.stations[0];
        if (!first) return;
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
  const readOnly = Boolean(lock && lock.mine === false);

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

  async function resumeDraft() {
    const data = await apiGet<{
      draft: { stations: StationSummary[]; conflict: boolean } | null;
    }>(`/api/projects/${projectId}/draft`);
    if (data.draft?.stations) setViewStations(data.draft.stations);
    setDraftPrompt(false);
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
        <button type="button" className="primary" onClick={() => setWizard(true)}>
          관측소 위저드
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
        <button
          type="button"
          onClick={() =>
            apiText(`/api/projects/${projectId}/xml`)
              .then(setXml)
              .catch((err: Error) => setError(err.message))
          }
        >
          StationXML
        </button>
      </div>
      {lock ? (
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
          {stations.map((sta) => (
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
                {sta.channels.map((ch) => (
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
              key={`${selected.station_path}-${selected.latitude}`}
              projectId={projectId}
              station={selected}
              disabled={readOnly}
            />
          ) : null}
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
      {xml ? <pre className="xml">{xml}</pre> : null}
    </div>
  );
}
