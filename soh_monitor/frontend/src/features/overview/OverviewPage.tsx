import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, type StationDto, type TopologyEdgeDto, type TopologyRegionDto } from "../../api/client";
import { SeverityBadge } from "../../components/SeverityBadge";
import { collectorGrafanaLink, fleetGrafanaLink, kioskGrafanaLink } from "../../lib/grafana";

const KOREA = { minLat: 33.0, maxLat: 38.8, minLon: 124.5, maxLon: 132.0 };

function project(station: StationDto): { x: number; y: number } | null {
  if (station.latitude == null || station.longitude == null) return null;
  const x = ((station.longitude - KOREA.minLon) / (KOREA.maxLon - KOREA.minLon)) * 100;
  const y = (1 - (station.latitude - KOREA.minLat) / (KOREA.maxLat - KOREA.minLat)) * 100;
  if (x < 0 || x > 100 || y < 0 || y > 100) return { x: Math.min(98, Math.max(2, x)), y: Math.min(98, Math.max(2, y)) };
  return { x, y };
}

const SHAPE: Record<string, string> = {
  OK: "map-ok",
  WARNING: "map-warning",
  CRITICAL: "map-critical",
  UNKNOWN: "map-unknown",
};

export function StationMap({ stations }: { stations: StationDto[] }) {
  const plotted = stations
    .map((station) => ({ station, point: project(station) }))
    .filter((item): item is { station: StationDto; point: { x: number; y: number } } => item.point !== null);

  return (
    <div className="station-map" role="img" aria-label="관측소 위치와 상태">
      <div className="map-canvas">
        {plotted.map(({ station, point }) => (
          <Link
            key={station.id}
            to={`/stations/${station.id}`}
            className={`map-mark ${SHAPE[station.worstSeverity ?? "UNKNOWN"] ?? "map-unknown"}`}
            style={{ left: `${point.x}%`, top: `${point.y}%` }}
            title={`${station.stationCode} ${station.name} ${station.worstSeverity ?? "UNKNOWN"}`}
          >
            <span className="map-icon" aria-hidden="true">
              {(station.worstSeverity ?? "UNKNOWN") === "CRITICAL"
                ? "▲"
                : (station.worstSeverity ?? "UNKNOWN") === "WARNING"
                  ? "◆"
                  : (station.worstSeverity ?? "UNKNOWN") === "OK"
                    ? "●"
                    : "■"}
            </span>
            <span className="map-code">{station.stationCode}</span>
          </Link>
        ))}
      </div>
      <p className="muted">
        색과 도형을 함께 쓴다. 원=정상, 마름모=주의, 세모=장애, 네모=확인 불가. 위경도가 없는 관측소는 지도에 올리지 않는다.
      </p>
    </div>
  );
}

export function OverviewPage() {
  const summary = useQuery({
    queryKey: ["fleet-summary"],
    queryFn: api.fleetSummary,
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const stations = useQuery({
    queryKey: ["stations"],
    queryFn: () => api.stations(),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const incidents = useQuery({
    queryKey: ["incidents", "open"],
    queryFn: () => api.incidents("open"),
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });
  const topology = useQuery({
    queryKey: ["fleet-topology"],
    queryFn: api.fleetTopology,
    refetchInterval: 15_000,
    placeholderData: keepPreviousData,
  });

  const fleet = summary.data;
  const connectivity = fleet?.connectivity ?? {};
  const latestSuccess = (stations.data?.stations ?? [])
    .map((item) => item.lastSuccessAt)
    .filter((item): item is string => Boolean(item))
    .sort()
    .at(-1);

  return (
    <>
      <h1 className="page-title">통합 현황</h1>
      <p className="page-subtitle">15초마다 갱신한다. 갱신 중에도 목록이 비워지지 않는다.</p>
      <div className="toolbar">
        <a className="btn ghost" href={fleetGrafanaLink()} target="_blank" rel="noreferrer">
          Grafana 함대
        </a>
        <a className="btn ghost" href={kioskGrafanaLink()} target="_blank" rel="noreferrer">
          관제 화면
        </a>
        <a className="btn ghost" href={collectorGrafanaLink()} target="_blank" rel="noreferrer">
          수집기 운영
        </a>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <div className="label">장비</div>
          <div className="value">{fleet?.deviceCount ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="label">열린 장애</div>
          <div className="value">{fleet?.openIncidents ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="label">낡은 상태</div>
          <div className="value">{fleet?.staleStates ?? "—"}</div>
        </div>
        <div className="stat">
          <div className="label">통신 정상</div>
          <div className="value">{connectivity.OK ?? 0}</div>
        </div>
        <div className="stat">
          <div className="label">통신 장애</div>
          <div className="value">{(connectivity.CRITICAL ?? 0) + (connectivity.WARNING ?? 0)}</div>
        </div>
        <div className="stat">
          <div className="label">마지막 수집</div>
          <div className="value stat-time">{latestSuccess?.replace("T", " ").slice(0, 19) ?? "—"}</div>
        </div>
      </div>

      <div className="split">
        <div className="card">
          <h2>관측소 지도</h2>
          <StationMap stations={stations.data?.stations ?? []} />
        </div>
        <div className="card">
          <h2>수집 방식</h2>
          <table>
            <thead>
              <tr>
                <th>방식</th>
                <th>관측소</th>
              </tr>
            </thead>
            <tbody>
              {["DIRECT", "EDGE", "MIXED"].map((mode) => (
                <tr key={mode}>
                  <td>{mode}</td>
                  <td>{(stations.data?.stations ?? []).filter((item) => item.collectionMode === mode).length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>지역 토폴로지</h2>
        <p className="muted">지역 → Edge → 관측소. Edge 가 끊기면 하위 관측소는 EDGE UNREACHABLE 이다.</p>
        <div className="topology">
          {(topology.data?.regions ?? []).map((region: TopologyRegionDto) => (
            <div className="topology-region" key={region.id}>
              <strong>
                {region.regionCode} {region.name}
              </strong>
              {region.edges.map((edge: TopologyEdgeDto) => (
                <div className="topology-edge" key={edge.id}>
                  <Link to={`/edges/${edge.id}`}>
                    {edge.edgeCode} · {edge.status}
                  </Link>
                  <div className="topology-stations">
                    {edge.stations.map((station) => (
                      <Link
                        key={station.id}
                        className={`topology-station ${station.edgeUnreachable ? "unreachable" : ""}`}
                        to={`/stations/${station.id}`}
                      >
                        {station.stationCode}{" "}
                        <SeverityBadge severity={station.worstSeverity} />
                        {station.edgeUnreachable ? " EDGE UNREACHABLE" : ""}
                      </Link>
                    ))}
                  </div>
                </div>
              ))}
              {region.stationsWithoutEdge.length > 0 && (
                <div className="topology-edge">
                  <span className="muted">Edge 없음 (DIRECT)</span>
                  <div className="topology-stations">
                    {region.stationsWithoutEdge.map((station) => (
                      <Link key={station.id} className="topology-station" to={`/stations/${station.id}`}>
                        {station.stationCode} <SeverityBadge severity={station.worstSeverity} />
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
          {(topology.data?.unassigned.edges.length || topology.data?.unassigned.stations.length) ? (
            <div className="topology-region">
              <strong>미지정 지역</strong>
              {(topology.data?.unassigned.edges ?? []).map((edge) => (
                <div className="topology-edge" key={edge.id}>
                  <Link to={`/edges/${edge.id}`}>
                    {edge.edgeCode} · {edge.status}
                  </Link>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="card">
        <h2>현재 장애</h2>
        {(incidents.data?.incidents.length ?? 0) === 0 ? (
          <p className="muted">열린 장애가 없다.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>관측소</th>
                <th>상태</th>
                <th>제목</th>
                <th>최근 관측</th>
              </tr>
            </thead>
            <tbody>
            {(incidents.data?.incidents ?? [])
              .filter((incident) => !incident.suppressedByEdge)
              .slice(0, 12)
              .map((incident) => (
                <tr key={incident.incidentId}>
                  <td>{incident.stationCode ?? "—"}</td>
                  <td>
                    <SeverityBadge severity={incident.severity} />
                  </td>
                  <td>
                    <Link to="/incidents">{incident.title}</Link>
                  </td>
                  <td>{incident.lastObservedAt?.replace("T", " ").slice(0, 19) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
