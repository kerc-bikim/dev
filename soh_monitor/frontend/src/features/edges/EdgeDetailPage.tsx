import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { SeverityBadge } from "../../components/SeverityBadge";

function formatWhen(value: string | null | undefined): string {
  return value ? value.replace("T", " ").slice(0, 19) : "—";
}

export function EdgeDetailPage() {
  const { edgeId = "" } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [deviceId, setDeviceId] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const edge = useQuery({
    queryKey: ["edge", edgeId],
    queryFn: () => api.edge(edgeId),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
    enabled: Boolean(edgeId),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["edge", edgeId] });
    void queryClient.invalidateQueries({ queryKey: ["edges"] });
  }

  const reissue = useMutation({
    mutationFn: () => api.reissueEnrollment(edgeId),
    onSuccess: (body) => {
      setToken(body.enrollmentToken);
      setError(null);
      refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Token 을 발급하지 못했다"),
  });
  const revoke = useMutation({
    mutationFn: () => api.revokeEdge(edgeId),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "폐기하지 못했다"),
  });
  const assign = useMutation({
    mutationFn: () => api.assignDevice(edgeId, deviceId),
    onSuccess: () => {
      setDeviceId("");
      setError(null);
      refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "할당하지 못했다"),
  });
  const unassign = useMutation({
    mutationFn: (id: string) => api.unassignDevice(edgeId, id),
    onSuccess: () => refresh(),
  });

  const body = edge.data?.edge;
  const used = body?.spoolUsedBytes ?? 0;
  const limit = body?.spoolLimitBytes ?? 0;
  const ratio = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;

  return (
    <>
      <h1 className="page-title">{body?.name ?? "Edge"}</h1>
      <p className="page-subtitle">
        <Link to="/edges">목록</Link> · {body?.edgeCode} · {body?.status}
      </p>
      {error && <div className="notice warn">{error}</div>}
      {token && (
        <div className="notice">
          등록 Token (지금만 보인다): <code>{token}</code>
        </div>
      )}
      {!body ? (
        <p className="muted">불러오는 중</p>
      ) : (
        <>
          <div className="stat-grid">
            <div className="stat">
              <div className="label">통신</div>
              <div className="value">
                <SeverityBadge severity={body.health?.connectivityStatus} />
              </div>
            </div>
            <div className="stat">
              <div className="label">수집기</div>
              <div className="value">
                <SeverityBadge severity={body.health?.collectorStatus} />
              </div>
            </div>
            <div className="stat">
              <div className="label">인증서</div>
              <div className="value">
                <SeverityBadge severity={body.health?.certificateStatus} />
              </div>
            </div>
            <div className="stat">
              <div className="label">대기 Batch</div>
              <div className="value">{body.health?.pendingBatches ?? "—"}</div>
            </div>
            <div className="stat">
              <div className="label">최고령 대기</div>
              <div className="value">
                {body.health?.oldestPendingAgeSeconds != null
                  ? `${Math.round(body.health.oldestPendingAgeSeconds)}s`
                  : "—"}
              </div>
            </div>
            <div className="stat">
              <div className="label">설정 버전</div>
              <div className="value">
                {body.lastConfigAppliedVersion}/{body.lastConfigVersion}
              </div>
            </div>
          </div>

          <div className="split">
            <div className="card">
              <h2>Spool</h2>
              <div className="spool-bar" aria-label="Spool 사용량">
                <span style={{ width: `${ratio}%` }} />
              </div>
              <p className="muted">
                {used.toLocaleString()} / {limit ? limit.toLocaleString() : "—"} bytes
              </p>
              <p>마지막 업로드 {formatWhen(body.lastUploadAt)}</p>
              <p>마지막 Heartbeat {formatWhen(body.lastHeartbeatAt)}</p>
            </div>
            <div className="card">
              <h2>인증서·프로그램</h2>
              <p>버전 {body.softwareVersion ?? "—"}</p>
              <p>일련번호 {body.certificateSerial ?? "—"}</p>
              <p>만료 {formatWhen(body.certificateExpiresAt)}</p>
              <p>폐기 {formatWhen(body.revokedAt)}</p>
              <p>
                Adapter{" "}
                {Object.keys(body.installedAdapters || {}).join(", ") || "아직 보고 없음"}
              </p>
              {can("administer") && body.status !== "DISABLED" && (
                <div className="toolbar">
                  <button className="btn ghost" type="button" onClick={() => reissue.mutate()}>
                    등록 Token 재발급
                  </button>
                  <button className="btn ghost" type="button" onClick={() => revoke.mutate()}>
                    인증서 폐기
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <h2>할당된 기록계</h2>
            {can("administer") && (
              <div className="toolbar">
                <input
                  placeholder="장비 UUID"
                  value={deviceId}
                  onChange={(event) => setDeviceId(event.target.value)}
                />
                <button className="btn primary" type="button" disabled={!deviceId} onClick={() => assign.mutate()}>
                  할당
                </button>
              </div>
            )}
            <table>
              <thead>
                <tr>
                  <th>관측소</th>
                  <th>장비</th>
                  <th>Adapter</th>
                  <th>epoch</th>
                  {can("administer") && <th></th>}
                </tr>
              </thead>
              <tbody>
                {(body.assignments ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.stationId ? (
                        <Link to={`/stations/${row.stationId}`}>{row.stationCode ?? row.stationId}</Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{row.label ?? row.deviceId}</td>
                    <td>{row.adapterKey ?? "—"}</td>
                    <td>{row.assignmentEpoch}</td>
                    {can("administer") && (
                      <td>
                        <button className="btn ghost" type="button" onClick={() => unassign.mutate(row.deviceId)}>
                          해제
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {(body.assignments?.length ?? 0) === 0 && <p className="muted">할당된 장비가 없다.</p>}
          </div>
        </>
      )}
    </>
  );
}
