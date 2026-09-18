import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { SeverityBadge } from "../../components/SeverityBadge";
import { stationGrafanaLink } from "../../lib/grafana";

const TABS = [
  { id: "summary", label: "요약" },
  { id: "power", label: "전원" },
  { id: "timing", label: "시각·GNSS" },
  { id: "sensor", label: "센서" },
  { id: "storage", label: "저장소" },
  { id: "data", label: "데이터" },
  { id: "external", label: "외부 SOH" },
  { id: "history", label: "수집 이력" },
  { id: "settings", label: "설정" },
  { id: "incidents", label: "장애" },
] as const;

const CATEGORY_TAB: Record<string, string> = {
  power: "power",
  timing: "timing",
  gnss: "timing",
  sensor: "sensor",
  storage: "storage",
  archive: "storage",
  acquisition: "data",
  external_soh: "external",
  connectivity: "summary",
  device: "summary",
};

export function StationDetailPage() {
  const { stationId = "" } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("summary");

  const detail = useQuery({
    queryKey: ["station", stationId],
    queryFn: () => api.station(stationId),
    enabled: Boolean(stationId),
  });
  const health = useQuery({
    queryKey: ["station-health", stationId],
    queryFn: () => api.stationHealth(stationId),
    enabled: Boolean(stationId),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const deviceId = detail.data?.devices[0]?.id;
  const deviceHealth = useQuery({
    queryKey: ["device-health", deviceId],
    queryFn: () => api.deviceHealth(deviceId!),
    enabled: Boolean(deviceId),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const runs = useQuery({
    queryKey: ["poll-runs", deviceId],
    queryFn: () => api.pollRuns(deviceId!),
    enabled: Boolean(deviceId) && tab === "history",
  });
  const incidents = useQuery({
    queryKey: ["incidents", "open"],
    queryFn: () => api.incidents("open"),
    enabled: tab === "incidents",
  });

  const pollNow = useMutation({
    mutationFn: api.pollNow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["poll-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["device-health"] });
    },
  });

  if (detail.isLoading) return <p>관측소를 불러오는 중이다.</p>;
  if (!detail.data) return <div className="notice warn">관측소를 찾지 못했다.</div>;

  const station = detail.data.station;
  const device = detail.data.devices[0];
  const metrics = (deviceHealth.data?.metrics ?? []).filter((metric) => {
    if (tab === "summary") return true;
    return CATEGORY_TAB[metric.category] === tab;
  });

  return (
    <>
      <p>
        <Link to="/stations">← 목록</Link>
      </p>
      <h1 className="page-title">
        {station.networkCode}.{station.stationCode} {station.name}
      </h1>
      <p className="page-subtitle">
        종합 <SeverityBadge severity={health.data?.overall ?? station.worstSeverity} /> · 장비 {station.deviceCount}대
      </p>

      <div className="toolbar">
        {can("operate") && device && (
          <button className="btn ghost" type="button" onClick={() => pollNow.mutate(device.id)}>
            지금 수집
          </button>
        )}
        <a
          className="btn ghost"
          href={stationGrafanaLink(station.stationCode, tab)}
          target="_blank"
          rel="noreferrer"
        >
          Grafana에서 추세 보기
        </a>
      </div>

      <div className="tabs">
        {TABS.map((item) => (
          <button
            key={item.id}
            className={tab === item.id ? "active" : undefined}
            type="button"
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "settings" && (
        <div className="card">
          <h2>등록 정보</h2>
          <table>
            <tbody>
              <tr>
                <th>전원 구성</th>
                <td>{station.powerProfile ?? "—"}</td>
              </tr>
              <tr>
                <th>Adapter</th>
                <td>{device?.adapterKey ?? "—"}</td>
              </tr>
              <tr>
                <th>접속</th>
                <td>
                  {device?.endpoint
                    ? `${device.endpoint.scheme}://${device.endpoint.hostname}`
                    : "없음"}
                </td>
              </tr>
              <tr>
                <th>인증 참조</th>
                <td>{device?.endpoint?.credentialReference ?? "없음"}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {tab === "history" && (
        <div className="card">
          <h2>수집 이력</h2>
          <table>
            <thead>
              <tr>
                <th>시각</th>
                <th>결과</th>
                <th>지연</th>
                <th>오류</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data?.runs ?? []).map((run) => (
                <tr key={run.pollId}>
                  <td>{run.observedAt?.replace("T", " ").slice(0, 19)}</td>
                  <td>{run.success ? "성공" : "실패"}</td>
                  <td>{run.latencyMs ?? "—"}</td>
                  <td>{run.errorCode ?? run.errorMessage ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "incidents" && (
        <div className="card">
          <h2>이 관측소 장애</h2>
          <ul>
            {(incidents.data?.incidents ?? [])
              .filter((item) => item.stationCode === station.stationCode)
              .map((item) => (
                <li key={item.incidentId}>
                  <SeverityBadge severity={item.severity} /> {item.title}
                </li>
              ))}
          </ul>
        </div>
      )}

      {tab !== "settings" && tab !== "history" && tab !== "incidents" && (
        <div className="card">
          <h2>현재 값</h2>
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th>값</th>
                <th>상태</th>
                <th>지원</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((metric) => (
                <tr key={`${metric.metricKey}:${metric.dimension ?? ""}`}>
                  <td>
                    <code>{metric.metricKey}</code>
                    {metric.dimension ? ` [${metric.dimension}]` : ""}
                  </td>
                  <td>{metric.value ?? "—"}</td>
                  <td>
                    <SeverityBadge severity={metric.severity} />
                  </td>
                  <td>{metric.supportState}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {metrics.length === 0 && <p className="muted">이 분류의 현재 값이 없다. 아직 수집되지 않았거나 미지원이다.</p>}
        </div>
      )}
    </>
  );
}
