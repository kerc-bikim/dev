import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, type MaintenanceWindowDto } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { BusyButton } from "../../components/BusyButton";
import { SeverityBadge } from "../../components/SeverityBadge";
import { stationTabVisibility, type StationTabId } from "../../lib/capabilityTabs";
import { stationGrafanaLink } from "../../lib/grafana";

function DataSourceUriField({ deviceId, value }: { deviceId: string; value: string | null }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(value ?? "");
  const [notice, setNotice] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

  const save = useMutation({
    mutationFn: () => api.updateDevice(deviceId, { dataSourceUri: draft.trim() || null }),
    onSuccess: (body) => {
      const next = body.device.dataSourceUri;
      setDraft(next ?? "");
      setNotice({
        kind: "ok",
        text: next
          ? "데이터 서버 URI를 저장했다."
          : "데이터 서버 URI를 비웠다. 파형 검사는 미지원이다.",
      });
      void queryClient.invalidateQueries({ queryKey: ["station"] });
      void queryClient.invalidateQueries({ queryKey: ["device-capabilities"] });
      void queryClient.invalidateQueries({ queryKey: ["device-health"] });
    },
    onError: (err) =>
      setNotice({
        kind: "warn",
        text: err instanceof ApiError ? err.message : "저장에 실패했다",
      }),
  });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label className="field">
        <input
          type="text"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setNotice(null);
          }}
          placeholder="https://10.0.0.8/fdsnws/availability/1/query?net=KS&sta=A01&format=json"
          autoComplete="off"
          aria-label="데이터 서버 URI"
        />
        <small>http, https, fdsnws, seedlink 만 허용한다. 비우면 파형 검사는 미지원이다.</small>
      </label>
      <button className="btn primary" type="submit" disabled={save.isPending}>
        {save.isPending ? "저장 중" : "URI 저장"}
      </button>
      {notice && <div className={notice.kind === "warn" ? "notice warn" : "notice"}>{notice.text}</div>}
    </form>
  );
}

function ConnectionTestControl({
  deviceId,
  onResult,
}: {
  deviceId: string;
  onResult: (result: { kind: "ok" | "warn"; text: string } | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [controller, setController] = useState<AbortController | null>(null);

  async function run() {
    const abort = new AbortController();
    setController(abort);
    setBusy(true);
    onResult(null);
    try {
      const body = await api.testDeviceConnection(deviceId, abort.signal);
      if (body.queued) {
        onResult({ kind: "ok", text: body.message || "지역 Edge 가 연결 시험을 수행한다" });
        return;
      }
      const latency = body.latencyMs != null ? ` · ${Math.round(body.latencyMs)}ms` : "";
      const identity = body.identity?.instrumentId ? ` · ${body.identity.instrumentId}` : "";
      onResult({
        kind: body.reachable ? "ok" : "warn",
        text: `${body.message}${latency}${identity}`,
      });
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        onResult({ kind: "warn", text: "연결 시험을 취소했다" });
      } else {
        onResult({
          kind: "warn",
          text: err instanceof ApiError ? err.message : "연결 시험에 실패했다",
        });
      }
    } finally {
      setBusy(false);
      setController(null);
    }
  }

  return (
    <BusyButton
      className="btn ghost"
      busy={busy}
      onCancel={() => controller?.abort()}
      onClick={() => void run()}
    >
      연결 시험
    </BusyButton>
  );
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function toLocalInput(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatWhen(value: string | null | undefined): string {
  return value ? value.replace("T", " ").slice(0, 19) : "—";
}

function windowPhase(startsAt: string | null, endsAt: string | null, now = Date.now()): "진행" | "예정" | "종료" {
  const start = startsAt ? Date.parse(startsAt) : Number.NaN;
  const end = endsAt ? Date.parse(endsAt) : Number.NaN;
  if (Number.isFinite(start) && Number.isFinite(end) && start <= now && end >= now) return "진행";
  if (Number.isFinite(start) && start > now) return "예정";
  return "종료";
}

function defaultWindowRange(): { start: string; end: string } {
  const start = new Date();
  const end = new Date(start.getTime() + 2 * 60 * 60 * 1000);
  return { start: toLocalInput(start), end: toLocalInput(end) };
}

function MaintenanceWindowsCard({ stationId }: { stationId: string }) {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const range = defaultWindowRange();
  const [reason, setReason] = useState("");
  const [startsAt, setStartsAt] = useState(range.start);
  const [endsAt, setEndsAt] = useState(range.end);
  const [notice, setNotice] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

  const windows = useQuery({
    queryKey: ["maintenance", "station", stationId],
    queryFn: () => api.maintenanceWindows({ scope: "station", scopeId: stationId }),
    enabled: Boolean(stationId),
    refetchInterval: 15_000,
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["maintenance", "station", stationId] });
    void queryClient.invalidateQueries({ queryKey: ["station-health", stationId] });
  }

  const create = useMutation({
    mutationFn: () =>
      api.createMaintenanceWindow({
        scope: "station",
        scopeId: stationId,
        startsAt: new Date(startsAt).toISOString(),
        endsAt: new Date(endsAt).toISOString(),
        reason: reason.trim() || null,
        suppressAlerts: true,
      }),
    onSuccess: () => {
      setReason("");
      const next = defaultWindowRange();
      setStartsAt(next.start);
      setEndsAt(next.end);
      setNotice({ kind: "ok", text: "유지보수 창을 열었다. 이 시간대 알림은 억제된다." });
      refresh();
    },
    onError: (err) =>
      setNotice({
        kind: "warn",
        text: err instanceof ApiError ? err.message : "유지보수 창을 열지 못했다",
      }),
  });

  const close = useMutation({
    mutationFn: api.closeMaintenanceWindow,
    onSuccess: () => {
      setNotice({ kind: "ok", text: "유지보수 창을 닫았다." });
      refresh();
    },
    onError: (err) =>
      setNotice({
        kind: "warn",
        text: err instanceof ApiError ? err.message : "유지보수 창을 닫지 못했다",
      }),
  });

  const rows = windows.data?.windows ?? [];

  return (
    <div className="card">
      <h2>유지보수 창</h2>
      <p className="muted">열리면 알림은 억제되고 상태는 MAINTENANCE 로 남는다. 없는 값을 정상으로 바꾸지 않는다.</p>
      {notice && <div className={notice.kind === "warn" ? "notice warn" : "notice"}>{notice.text}</div>}
      <table>
        <thead>
          <tr>
            <th>상태</th>
            <th>시작</th>
            <th>종료</th>
            <th>사유</th>
            {can("operate") && <th></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((window) => {
            const phase = windowPhase(window.startsAt, window.endsAt);
            return (
              <tr key={window.id}>
                <td>{phase}</td>
                <td>{formatWhen(window.startsAt)}</td>
                <td>{formatWhen(window.endsAt)}</td>
                <td>{window.reason ?? "—"}</td>
                {can("operate") && (
                  <td>
                    {phase !== "종료" && (
                      <button
                        className="btn ghost"
                        type="button"
                        disabled={close.isPending}
                        onClick={() => close.mutate(window.id)}
                      >
                        지금 닫기
                      </button>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length === 0 && <p className="muted">등록된 유지보수 창이 없다.</p>}
      {can("operate") && (
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <label className="field">
            <span>시작</span>
            <input
              type="datetime-local"
              required
              value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)}
            />
          </label>
          <label className="field">
            <span>종료</span>
            <input
              type="datetime-local"
              required
              value={endsAt}
              onChange={(event) => setEndsAt(event.target.value)}
            />
          </label>
          <label className="field">
            <span>사유</span>
            <input
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="센서 교체"
            />
          </label>
          <div>
            <button className="btn primary" type="submit" disabled={create.isPending}>
              {create.isPending ? "여는 중" : "유지보수 열기"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

function activeStationWindow(windows: MaintenanceWindowDto[] | undefined): MaintenanceWindowDto | undefined {
  return (windows ?? []).find((item) => windowPhase(item.startsAt, item.endsAt) === "진행");
}

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
  const [tab, setTab] = useState<StationTabId>("summary");
  const [testNotice, setTestNotice] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

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

  const adapters = useQuery({
    queryKey: ["adapters"],
    queryFn: api.adapters,
  });
  const capabilities = useQuery({
    queryKey: ["device-capabilities", deviceId],
    queryFn: () => api.deviceCapabilities(deviceId!),
    enabled: Boolean(deviceId),
  });

  const windows = useQuery({
    queryKey: ["maintenance", "station", stationId],
    queryFn: () => api.maintenanceWindows({ scope: "station", scopeId: stationId }),
    enabled: Boolean(stationId),
    refetchInterval: 15_000,
  });

  const pollNow = useMutation({
    mutationFn: api.pollNow,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["poll-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["device-health"] });
      void queryClient.invalidateQueries({ queryKey: ["device-capabilities"] });
    },
  });

  if (detail.isLoading) return <p>관측소를 불러오는 중이다.</p>;
  if (!detail.data) return <div className="notice warn">관측소를 찾지 못했다.</div>;

  const station = detail.data.station;
  const device = detail.data.devices[0];
  const adapterCapabilities = (adapters.data?.adapters ?? []).find(
    (item) => item.adapterKey === device?.adapterKey,
  )?.capabilities;
  const tabs = stationTabVisibility(capabilities.data?.capabilities, adapterCapabilities);
  const activeTab = tabs.find((item) => item.id === tab && !item.unsupported) ? tab : "summary";
  const metrics = (deviceHealth.data?.metrics ?? []).filter((metric) => {
    if (activeTab === "summary") return true;
    return CATEGORY_TAB[metric.category] === activeTab;
  });
  const currentTabMeta = tabs.find((item) => item.id === activeTab);
  const activeWindow = activeStationWindow(windows.data?.windows);

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

      {activeWindow && (
        <div className="notice">
          유지보수 중이다. 알림은 억제되고 상태는 MAINTENANCE 로 남는다.
          {activeWindow.reason ? ` 사유: ${activeWindow.reason}` : ""}
        </div>
      )}

      <div className="toolbar">
        {can("operate") && device && (
          <>
            <button className="btn ghost" type="button" onClick={() => pollNow.mutate(device.id)}>
              지금 수집
            </button>
            <ConnectionTestControl deviceId={device.id} onResult={setTestNotice} />
          </>
        )}
        <a
          className="btn ghost"
          href={stationGrafanaLink(station.stationCode, activeTab)}
          target="_blank"
          rel="noreferrer"
        >
          Grafana에서 추세 보기
        </a>
      </div>
      {testNotice && (
        <div className={testNotice.kind === "warn" ? "notice warn" : "notice"}>{testNotice.text}</div>
      )}

      <div className="tabs">
        {tabs.map((item) => (
          <button
            key={item.id}
            className={activeTab === item.id ? "active" : item.unsupported ? "unsupported" : undefined}
            type="button"
            disabled={item.unsupported}
            onClick={() => {
              if (!item.unsupported) setTab(item.id);
            }}
          >
            {item.unsupported ? `${item.label} · 미지원` : item.label}
          </button>
        ))}
      </div>

      {activeTab === "settings" && (
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
              <tr>
                <th>데이터 서버</th>
                <td>
                  {can("configure") && device ? (
                    <DataSourceUriField
                      key={device.id}
                      deviceId={device.id}
                      value={device.dataSourceUri}
                    />
                  ) : (
                    device?.dataSourceUri ?? "없음 (파형 검사 미지원)"
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {activeTab === "settings" && <MaintenanceWindowsCard stationId={station.id} />}

      {activeTab === "history" && (
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

      {activeTab === "incidents" && (
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

      {activeTab !== "settings" && activeTab !== "history" && activeTab !== "incidents" && (
        <div className="card">
          <h2>{currentTabMeta?.unsupported ? `${currentTabMeta.label} 미지원` : "현재 값"}</h2>
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
