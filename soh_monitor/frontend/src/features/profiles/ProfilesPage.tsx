import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ApiError, api, type MetricProfileDto, type ProfileMetricDto } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";

function summarize(entries: ProfileMetricDto[]): string {
  const on = entries.filter((item) => item.enabled).length;
  const alerting = entries.filter((item) => item.alertingEnabled).length;
  return `감시 ${on} · 알림 ${alerting}`;
}

function entriesDiff(before: ProfileMetricDto[], after: ProfileMetricDto[]): string[] {
  const prev = new Map(before.map((item) => [item.metricKey, JSON.stringify(item)]));
  const next = new Map(after.map((item) => [item.metricKey, JSON.stringify(item)]));
  const changes: string[] = [];
  for (const [key, value] of next) {
    if (!prev.has(key)) changes.push(`${key} 추가`);
    else if (prev.get(key) !== value) changes.push(`${key} 변경`);
  }
  for (const key of prev.keys()) {
    if (!next.has(key)) changes.push(`${key} 제거`);
  }
  return changes;
}

export function ProfilesPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const collections = useQuery({ queryKey: ["collection-profiles"], queryFn: api.collectionProfiles });
  const metrics = useQuery({ queryKey: ["metric-profiles"], queryFn: api.metricProfiles });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<string>("");
  const [message, setMessage] = useState<string | null>(null);

  const selected: MetricProfileDto | undefined = useMemo(
    () => (metrics.data?.profiles ?? []).find((item) => item.id === selectedId) ?? metrics.data?.profiles[0],
    [metrics.data, selectedId],
  );

  const original = selected ? JSON.stringify(selected.entries, null, 2) : "";
  const editing = draft || original;
  const parsedDraft = useMemo(() => {
    try {
      return JSON.parse(editing) as ProfileMetricDto[];
    } catch {
      return null;
    }
  }, [editing]);
  const diff = selected && parsedDraft ? entriesDiff(selected.entries, parsedDraft) : [];

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.updateMetricProfile(String(selected?.id), body),
    onSuccess: (body) => {
      setMessage(`저장했다. 영향 장비 ${body.profile.affectedDeviceCount}대`);
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: ["metric-profiles"] });
    },
    onError: (error) => {
      setMessage(error instanceof ApiError ? error.message : "저장에 실패했다");
    },
  });

  const clone = useMutation({
    mutationFn: () => {
      if (!selected || !parsedDraft) {
        throw new Error("복제할 프로파일이 없다");
      }
      return api.createMetricProfile({
        name: `${selected.name} 복사`,
        description: selected.description,
        isDefault: false,
        entries: parsedDraft,
      });
    },
    onSuccess: (body) => {
      setMessage(`복제했다. 새 프로파일은 아직 장비 0대에 연결되어 있다.`);
      setSelectedId(body.profile.id);
      setDraft("");
      void queryClient.invalidateQueries({ queryKey: ["metric-profiles"] });
    },
    onError: (error) => {
      setMessage(error instanceof ApiError ? error.message : "복제에 실패했다");
    },
  });

  return (
    <>
      <h1 className="page-title">프로파일</h1>
      <p className="page-subtitle">프로파일을 바꾸면 그 프로파일을 쓰는 장비 수만큼 판정이 달라진다. 저장 전에 영향 범위와 변경 항목을 본다.</p>

      <div className="split">
        <div className="card">
          <h2>수집 프로파일</h2>
          <table>
            <thead>
              <tr>
                <th>이름</th>
                <th>주기</th>
                <th>영향</th>
              </tr>
            </thead>
            <tbody>
              {(collections.data?.profiles ?? []).map((profile) => (
                <tr key={profile.id}>
                  <td>{profile.name}</td>
                  <td>{profile.pollIntervalMinutes}분</td>
                  <td>{profile.affectedDeviceCount}대</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h2>Metric 프로파일</h2>
          <ul className="plain">
            {(metrics.data?.profiles ?? []).map((profile) => (
              <li key={profile.id}>
                <button
                  className="linkish"
                  type="button"
                  onClick={() => {
                    setSelectedId(profile.id);
                    setDraft("");
                    setMessage(null);
                  }}
                >
                  {profile.name}
                </button>{" "}
                <span className="muted">
                  {summarize(profile.entries)} · {profile.affectedDeviceCount}대
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {selected && (
        <div className="card">
          <h2>
            {selected.name} · 영향 {selected.affectedDeviceCount}대
          </h2>
          {message && <div className="notice">{message}</div>}
          <p className="muted">조건은 JSON 구조다. 문자열 표현식을 넣지 않는다.</p>
          <textarea
            className="json-editor"
            value={editing}
            onChange={(event) => setDraft(event.target.value)}
            readOnly={!can("configure")}
            rows={18}
          />
          {parsedDraft === null && <div className="notice warn">JSON 형식이 잘못됐다</div>}
          {diff.length > 0 && (
            <div className="notice">
              저장 전 차이 {diff.length}건: {diff.slice(0, 12).join(", ")}
              {diff.length > 12 ? ` 외 ${diff.length - 12}건` : ""}
            </div>
          )}
          {can("configure") && (
            <div className="toolbar">
              <button
                className="btn primary"
                type="button"
                disabled={save.isPending || !draft || draft === original || parsedDraft === null}
                onClick={() => {
                  save.mutate({ name: selected.name, description: selected.description, entries: parsedDraft });
                }}
              >
                저장
              </button>
              <button
                className="btn ghost"
                type="button"
                disabled={clone.isPending || parsedDraft === null}
                onClick={() => clone.mutate()}
              >
                이 내용으로 복제
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
