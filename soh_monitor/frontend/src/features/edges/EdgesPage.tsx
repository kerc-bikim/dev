import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { SeverityBadge } from "../../components/SeverityBadge";

function formatWhen(value: string | null | undefined): string {
  return value ? value.replace("T", " ").slice(0, 19) : "—";
}

export function EdgesPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("edge-region-a-01");
  const [name, setName] = useState("지역 Edge");
  const [regionId, setRegionId] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["edges"],
    queryFn: api.edges,
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const regions = useQuery({ queryKey: ["regions"], queryFn: api.regions });

  const create = useMutation({
    mutationFn: () =>
      api.createEdge({
        edgeCode: code,
        name,
        regionId: regionId || null,
      }),
    onSuccess: (body) => {
      setToken(body.edge.enrollmentToken ?? null);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["edges"] });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Edge 를 만들지 못했다");
    },
  });

  return (
    <>
      <h1 className="page-title">Edge Collector</h1>
      <p className="page-subtitle">
        마지막 Heartbeat 와 Spool, 인증서 상태를 본다. 등록 Token 은 한 번만 보여 준다.
      </p>
      {error && <div className="notice warn">{error}</div>}
      {token && (
        <div className="notice">
          등록 Token (지금만 보인다): <code>{token}</code>
        </div>
      )}
      {can("administer") && (
        <div className="card form-grid">
          <label className="field">
            <span>Edge 코드</span>
            <input value={code} onChange={(event) => setCode(event.target.value)} />
          </label>
          <label className="field">
            <span>이름</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field">
            <span>지역</span>
            <select value={regionId} onChange={(event) => setRegionId(event.target.value)}>
              <option value="">미지정</option>
              {(regions.data?.regions ?? []).map((region) => (
                <option key={region.id} value={region.id}>
                  {region.regionCode} {region.name}
                </option>
              ))}
            </select>
          </label>
          <button className="btn primary" type="button" onClick={() => create.mutate()}>
            Edge 등록
          </button>
        </div>
      )}
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>코드</th>
              <th>이름</th>
              <th>상태</th>
              <th>통신</th>
              <th>Heartbeat</th>
              <th>Spool</th>
              <th>버전</th>
            </tr>
          </thead>
          <tbody>
            {(list.data?.edges ?? []).map((edge) => {
              const used = edge.spoolUsedBytes ?? 0;
              const limit = edge.spoolLimitBytes ?? 0;
              const ratio = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
              return (
                <tr key={edge.id}>
                  <td>
                    <Link to={`/edges/${edge.id}`}>{edge.edgeCode}</Link>
                  </td>
                  <td>{edge.name}</td>
                  <td>{edge.status}</td>
                  <td>
                    <SeverityBadge severity={edge.health?.connectivityStatus} />
                  </td>
                  <td>{formatWhen(edge.lastHeartbeatAt)}</td>
                  <td>
                    {limit ? `${ratio}%` : "—"}
                    {edge.health?.pendingBatches != null ? ` · 대기 ${edge.health.pendingBatches}` : ""}
                  </td>
                  <td>{edge.softwareVersion ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {(list.data?.edges.length ?? 0) === 0 && <p className="muted">등록된 Edge 가 없다.</p>}
      </div>
    </>
  );
}
