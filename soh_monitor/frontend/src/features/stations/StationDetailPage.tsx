import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, type EndpointDto, type ExternalSohDto, type MaintenanceWindowDto, type MetricOverrideDto, type SensorDto } from "../../api/client";
import { useAuth } from "../../auth/AuthProvider";
import { BusyButton } from "../../components/BusyButton";
import { SeverityBadge } from "../../components/SeverityBadge";
import { METRIC_DEFINITIONS } from "../../generated/metrics";
import { stationTabVisibility, type StationTabId } from "../../lib/capabilityTabs";
import { stationGrafanaLink } from "../../lib/grafana";

function EndpointSettingsField({
  deviceId,
  endpoint,
}: {
  deviceId: string;
  endpoint: EndpointDto | null;
}) {
  const queryClient = useQueryClient();
  const [hostname, setHostname] = useState(endpoint?.hostname ?? "");
  const [credential, setCredential] = useState(endpoint?.credentialReference ?? "");
  const [notice, setNotice] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

  const save = useMutation({
    mutationFn: () =>
      api.updateDevice(deviceId, {
        endpoint: {
          scheme: endpoint?.scheme ?? "http",
          hostname: hostname.trim(),
          port: endpoint?.port ?? null,
          basePath: endpoint?.basePath ?? "/",
          tlsVerify: endpoint?.tlsVerify ?? true,
          credentialReference: credential.trim() || null,
          connectTimeoutMs: endpoint?.connectTimeoutMs ?? 5000,
          requestTimeoutMs: endpoint?.requestTimeoutMs ?? 15000,
          connectionOptions: endpoint?.connectionOptions ?? {},
        },
      }),
    onSuccess: (body) => {
      const next = body.device.endpoint;
      setHostname(next?.hostname ?? "");
      setCredential(next?.credentialReference ?? "");
      setNotice({ kind: "ok", text: "접속 호스트와 인증 참조를 저장했다." });
      void queryClient.invalidateQueries({ queryKey: ["station"] });
    },
    onError: (err) =>
      setNotice({
        kind: "warn",
        text: err instanceof ApiError ? err.message : "저장에 실패했다",
      }),
  });

  const scheme = endpoint?.scheme ?? "http";

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label className="field">
        <span>호스트</span>
        <input
          type="text"
          value={hostname}
          onChange={(event) => {
            setHostname(event.target.value);
            setNotice(null);
          }}
          placeholder={`${scheme}://10.10.1.20`}
          autoComplete="off"
          aria-label="접속 호스트"
        />
        <small>허용 대역(사설망)만 저장한다. 스킴은 {scheme} 이다.</small>
      </label>
      <label className="field">
        <span>인증 참조</span>
        <input
          type="text"
          value={credential}
          onChange={(event) => {
            setCredential(event.target.value);
            setNotice(null);
          }}
          placeholder="env:SOH_DEVICE_PW_C11 또는 file:/run/secrets/..."
          autoComplete="off"
          aria-label="인증 참조"
        />
        <small>비밀번호 평문은 저장하지 않는다. env: 또는 file: 만 받는다.</small>
      </label>
      <button className="btn primary" type="submit" disabled={save.isPending}>
        {save.isPending ? "저장 중" : "접속 저장"}
      </button>
      {notice && <div className={notice.kind === "warn" ? "notice warn" : "notice"}>{notice.text}</div>}
    </form>
  );
}

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

function CollectionToggle({ deviceId, enabled }: { deviceId: string; enabled: boolean }) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

  const save = useMutation({
    mutationFn: (next: boolean) => api.updateDevice(deviceId, { enabled: next }),
    onSuccess: (body) => {
      const next = body.device.enabled;
      setNotice({
        kind: "ok",
        text: next
          ? "수집을 켰다. 다음 Tick 부터 다시 모은다."
          : "수집을 껐다. 상태는 수집 제외다.",
      });
      void queryClient.invalidateQueries({ queryKey: ["station"] });
      void queryClient.invalidateQueries({ queryKey: ["station-health"] });
      void queryClient.invalidateQueries({ queryKey: ["device-health"] });
      void queryClient.invalidateQueries({ queryKey: ["stations"] });
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
        save.mutate(!enabled);
      }}
    >
      <p>{enabled ? "수집 중" : "수집 꺼짐"}</p>
      <small className="muted">끄면 스케줄과 지금 수집이 멈춘다. 꺼진 동안 상태는 수집 제외다.</small>
      <div>
        <button className="btn primary" type="submit" disabled={save.isPending}>
          {save.isPending ? "저장 중" : enabled ? "수집 끄기" : "수집 켜기"}
        </button>
      </div>
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

function SohPreviewControl({
  deviceId,
  onResult,
}: {
  deviceId: string;
  onResult: (result: { kind: "ok" | "warn"; text: string; payload?: unknown } | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [controller, setController] = useState<AbortController | null>(null);

  async function run() {
    const abort = new AbortController();
    setController(abort);
    setBusy(true);
    onResult(null);
    try {
      const body = await api.sohPreview(deviceId, abort.signal);
      if (!body.success) {
        onResult({
          kind: "warn",
          text: body.errorMessage || body.errorCode || "미리보기에 실패했다",
        });
        return;
      }
      onResult({
        kind: "ok",
        text: "Adapter 가 민감정보를 지운 SOH 원본이다. 없는 값은 정상으로 보이지 않는다.",
        payload: body.payload,
      });
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        onResult({ kind: "warn", text: "미리보기를 취소했다" });
      } else {
        onResult({
          kind: "warn",
          text: err instanceof ApiError ? err.message : "미리보기에 실패했다",
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
      SOH 미리보기
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

const NUMERIC_OPS = [">=", "<=", ">", "<", "==", "!=", "abs>="];
const OVERRIDE_METRICS = METRIC_DEFINITIONS.filter(
  (item) => item.valueType === "float" || item.valueType === "integer",
);

type OverrideDraft = {
  metricKey: string;
  dimensionValue: string;
  warningOp: string;
  warningValue: string;
  criticalOp: string;
  criticalValue: string;
  reason: string;
};

function parseNumericCondition(condition: Record<string, unknown> | null | undefined): { op: string; value: string } {
  if (!condition || typeof condition.op !== "string" || condition.value == null) {
    return { op: "", value: "" };
  }
  return { op: condition.op, value: String(condition.value) };
}

function toOverrideDraft(row: MetricOverrideDto): OverrideDraft {
  const warning = parseNumericCondition(row.warningCondition);
  const critical = parseNumericCondition(row.criticalCondition);
  return {
    metricKey: row.metricKey,
    dimensionValue: row.dimensionValue ?? "",
    warningOp: warning.op,
    warningValue: warning.value,
    criticalOp: critical.op,
    criticalValue: critical.value,
    reason: row.reason ?? "",
  };
}

function emptyOverrideDraft(): OverrideDraft {
  return {
    metricKey: "power.input_voltage_v",
    dimensionValue: "",
    warningOp: "<=",
    warningValue: "11.8",
    criticalOp: "<=",
    criticalValue: "11.0",
    reason: "",
  };
}

function conditionPayload(op: string, value: string): Record<string, unknown> {
  if (!op || value.trim() === "") return {};
  return { op, value: Number(value) };
}

function formatCondition(condition: Record<string, unknown> | null | undefined): string {
  if (!condition || Object.keys(condition).length === 0) return "—";
  if (typeof condition.op === "string" && condition.value != null) {
    return `${condition.op} ${condition.value}`;
  }
  if (condition.op === "outside" || condition.op === "inside") {
    return `${condition.op} ${condition.min}~${condition.max}`;
  }
  return JSON.stringify(condition);
}

function MetricOverridesCard({ deviceId }: { deviceId: string }) {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<OverrideDraft[] | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

  const overrides = useQuery({
    queryKey: ["device-overrides", deviceId],
    queryFn: () => api.deviceOverrides(deviceId),
    enabled: Boolean(deviceId),
  });

  const rows = draft ?? (overrides.data?.overrides ?? []).map(toOverrideDraft);

  function patch(index: number, next: Partial<OverrideDraft>) {
    setDraft(rows.map((row, current) => (current === index ? { ...row, ...next } : row)));
    setNotice(null);
  }

  const save = useMutation({
    mutationFn: () =>
      api.replaceDeviceOverrides(
        deviceId,
        rows
          .filter((row) => row.metricKey)
          .map((row) => ({
            metricKey: row.metricKey,
            dimensionValue: row.dimensionValue.trim() || "",
            enabled: true,
            alertingEnabled: true,
            warningCondition: conditionPayload(row.warningOp, row.warningValue),
            criticalCondition: conditionPayload(row.criticalOp, row.criticalValue),
            reason: row.reason.trim() || null,
          })),
      ),
    onSuccess: (body) => {
      setDraft(body.overrides.map(toOverrideDraft));
      setNotice({
        kind: "ok",
        text: body.overrides.length
          ? `Override ${body.overrides.length}건을 저장했다.`
          : "장비 Override 를 비웠다. 프로파일 기본값을 쓴다.",
      });
      void queryClient.invalidateQueries({ queryKey: ["device-overrides", deviceId] });
      void queryClient.invalidateQueries({ queryKey: ["device-health"] });
    },
    onError: (err) =>
      setNotice({
        kind: "warn",
        text: err instanceof ApiError ? err.message : "저장에 실패했다",
      }),
  });

  return (
    <div className="card">
      <h2>장비 Override</h2>
      <p className="muted">프로파일보다 이 장비만 임계를 달리 할 때 쓴다. 비우면 프로파일 기본값이다.</p>
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th>주의</th>
            <th>장애</th>
            <th>사유</th>
            {can("configure") && <th></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.metricKey}-${index}`}>
              <td>
                {can("configure") ? (
                  <select
                    value={row.metricKey}
                    aria-label="Override Metric"
                    onChange={(event) => patch(index, { metricKey: event.target.value })}
                  >
                    {OVERRIDE_METRICS.map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.displayName} ({item.key})
                      </option>
                    ))}
                    {row.metricKey && !OVERRIDE_METRICS.some((item) => item.key === row.metricKey) && (
                      <option value={row.metricKey}>{row.metricKey}</option>
                    )}
                  </select>
                ) : (
                  row.metricKey
                )}
              </td>
              <td>
                {can("configure") ? (
                  <div className="filter-row">
                    <select
                      value={row.warningOp}
                      aria-label="주의 연산"
                      onChange={(event) => patch(index, { warningOp: event.target.value })}
                    >
                      <option value="">없음</option>
                      {NUMERIC_OPS.map((op) => (
                        <option key={op} value={op}>
                          {op}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      step="any"
                      value={row.warningValue}
                      aria-label="주의 임계"
                      onChange={(event) => patch(index, { warningValue: event.target.value })}
                    />
                  </div>
                ) : (
                  formatCondition(overrides.data?.overrides[index]?.warningCondition)
                )}
              </td>
              <td>
                {can("configure") ? (
                  <div className="filter-row">
                    <select
                      value={row.criticalOp}
                      aria-label="장애 연산"
                      onChange={(event) => patch(index, { criticalOp: event.target.value })}
                    >
                      <option value="">없음</option>
                      {NUMERIC_OPS.map((op) => (
                        <option key={op} value={op}>
                          {op}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      step="any"
                      value={row.criticalValue}
                      aria-label="장애 임계"
                      onChange={(event) => patch(index, { criticalValue: event.target.value })}
                    />
                  </div>
                ) : (
                  formatCondition(overrides.data?.overrides[index]?.criticalCondition)
                )}
              </td>
              <td>
                {can("configure") ? (
                  <input
                    type="text"
                    value={row.reason}
                    aria-label="Override 사유"
                    onChange={(event) => patch(index, { reason: event.target.value })}
                    placeholder="12V 배터리"
                  />
                ) : (
                  row.reason || "—"
                )}
              </td>
              {can("configure") && (
                <td>
                  <button
                    className="btn ghost"
                    type="button"
                    onClick={() => {
                      setDraft(rows.filter((_, current) => current !== index));
                      setNotice(null);
                    }}
                  >
                    삭제
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="muted">장비 Override 가 없다. 프로파일 기본값을 쓴다.</p>}
      {can("configure") && (
        <div className="filter-row">
          <button
            className="btn ghost"
            type="button"
            onClick={() => {
              setDraft([...rows, emptyOverrideDraft()]);
              setNotice(null);
            }}
          >
            행 추가
          </button>
          <button className="btn primary" type="button" disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "저장 중" : "Override 저장"}
          </button>
        </div>
      )}
      {notice && <div className={notice.kind === "warn" ? "notice warn" : "notice"}>{notice.text}</div>}
    </div>
  );
}

function SensorsHardwareCard({
  deviceId,
  sensors,
  channels,
}: {
  deviceId: string;
  sensors: SensorDto[];
  channels: ExternalSohDto[];
}) {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [sensorDraft, setSensorDraft] = useState(() =>
    sensors.map((item) => ({
      port: item.port,
      model: item.model ?? "",
      axisCount: item.axisCount,
      axes: item.axes,
    })),
  );
  const [channelDraft, setChannelDraft] = useState(() =>
    channels.map((item) => ({
      channelNumber: item.channelNumber,
      name: item.name,
      scale: item.scale,
      offset: item.offset,
    })),
  );
  const [notice, setNotice] = useState<{ kind: "ok" | "warn"; text: string } | null>(null);

  const save = useMutation({
    mutationFn: async () => {
      const savedSensors = await api.replaceSensors(
        deviceId,
        sensorDraft
          .filter((item) => item.port.trim())
          .map((item) => ({
            port: item.port.trim(),
            model: item.model.trim() || null,
            axisCount: item.axisCount,
            axes: item.axes.map((axis) => ({
              axisCode: axis.axisCode,
              sohChannel: axis.sohChannel,
              warningThreshold: axis.warningThreshold,
              criticalThreshold: axis.criticalThreshold,
              unit: axis.unit,
            })),
          })),
      );
      const savedChannels = await api.replaceExternalSoh(
        deviceId,
        channelDraft
          .filter((item) => item.name.trim())
          .map((item) => ({
            channelNumber: item.channelNumber,
            name: item.name.trim(),
            scale: item.scale,
            offset: item.offset,
          })),
      );
      return { savedSensors, savedChannels };
    },
    onSuccess: (body) => {
      setSensorDraft(
        body.savedSensors.sensors.map((item) => ({
          port: item.port,
          model: item.model ?? "",
          axisCount: item.axisCount,
          axes: item.axes,
        })),
      );
      setChannelDraft(
        body.savedChannels.channels.map((item) => ({
          channelNumber: item.channelNumber,
          name: item.name,
          scale: item.scale,
          offset: item.offset,
        })),
      );
      setNotice({ kind: "ok", text: "센서와 외부 SOH 를 저장했다." });
      void queryClient.invalidateQueries({ queryKey: ["station"] });
      void queryClient.invalidateQueries({ queryKey: ["device-capabilities"] });
    },
    onError: (err) =>
      setNotice({
        kind: "warn",
        text: err instanceof ApiError ? err.message : "저장에 실패했다",
      }),
  });

  return (
    <div className="card">
      <h2>센서·외부 SOH</h2>
      <p className="muted">등록 뒤에도 센서 교체와 외부 채널을 맞춘다. 축을 생략하면 U/V/W 기본이다.</p>
      <table>
        <thead>
          <tr>
            <th>포트</th>
            <th>모델</th>
            <th>축</th>
            {can("configure") && <th></th>}
          </tr>
        </thead>
        <tbody>
          {sensorDraft.map((row, index) => (
            <tr key={`sensor-${index}`}>
              <td>
                {can("configure") ? (
                  <input
                    type="text"
                    value={row.port}
                    aria-label="센서 포트"
                    onChange={(event) => {
                      setNotice(null);
                      setSensorDraft((rows) =>
                        rows.map((item, current) =>
                          current === index ? { ...item, port: event.target.value } : item,
                        ),
                      );
                    }}
                  />
                ) : (
                  row.port
                )}
              </td>
              <td>
                {can("configure") ? (
                  <input
                    type="text"
                    value={row.model}
                    aria-label="센서 모델"
                    onChange={(event) => {
                      setNotice(null);
                      setSensorDraft((rows) =>
                        rows.map((item, current) =>
                          current === index ? { ...item, model: event.target.value } : item,
                        ),
                      );
                    }}
                  />
                ) : (
                  row.model || "—"
                )}
              </td>
              <td>{row.axisCount}</td>
              {can("configure") && (
                <td>
                  <button
                    className="btn ghost"
                    type="button"
                    onClick={() => {
                      setNotice(null);
                      setSensorDraft((rows) => rows.filter((_, current) => current !== index));
                    }}
                  >
                    삭제
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {sensorDraft.length === 0 && <p className="muted">등록된 센서가 없다.</p>}
      <table>
        <thead>
          <tr>
            <th>채널</th>
            <th>이름</th>
            <th>scale</th>
            <th>offset</th>
            {can("configure") && <th></th>}
          </tr>
        </thead>
        <tbody>
          {channelDraft.map((row, index) => (
            <tr key={`soh-${index}`}>
              <td>
                {can("configure") ? (
                  <input
                    type="number"
                    value={row.channelNumber}
                    aria-label="외부 SOH 채널"
                    onChange={(event) => {
                      setNotice(null);
                      setChannelDraft((rows) =>
                        rows.map((item, current) =>
                          current === index ? { ...item, channelNumber: Number(event.target.value) } : item,
                        ),
                      );
                    }}
                  />
                ) : (
                  row.channelNumber
                )}
              </td>
              <td>
                {can("configure") ? (
                  <input
                    type="text"
                    value={row.name}
                    aria-label="외부 SOH 이름"
                    onChange={(event) => {
                      setNotice(null);
                      setChannelDraft((rows) =>
                        rows.map((item, current) =>
                          current === index ? { ...item, name: event.target.value } : item,
                        ),
                      );
                    }}
                  />
                ) : (
                  row.name
                )}
              </td>
              <td>
                {can("configure") ? (
                  <input
                    type="number"
                    step="any"
                    value={row.scale}
                    aria-label="외부 SOH scale"
                    onChange={(event) => {
                      setNotice(null);
                      setChannelDraft((rows) =>
                        rows.map((item, current) =>
                          current === index ? { ...item, scale: Number(event.target.value) } : item,
                        ),
                      );
                    }}
                  />
                ) : (
                  row.scale
                )}
              </td>
              <td>
                {can("configure") ? (
                  <input
                    type="number"
                    step="any"
                    value={row.offset}
                    aria-label="외부 SOH offset"
                    onChange={(event) => {
                      setNotice(null);
                      setChannelDraft((rows) =>
                        rows.map((item, current) =>
                          current === index ? { ...item, offset: Number(event.target.value) } : item,
                        ),
                      );
                    }}
                  />
                ) : (
                  row.offset
                )}
              </td>
              {can("configure") && (
                <td>
                  <button
                    className="btn ghost"
                    type="button"
                    onClick={() => {
                      setNotice(null);
                      setChannelDraft((rows) => rows.filter((_, current) => current !== index));
                    }}
                  >
                    삭제
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {channelDraft.length === 0 && <p className="muted">외부 SOH 채널이 없다. 변환식은 value = raw × scale + offset 이다.</p>}
      {can("configure") && (
        <div className="filter-row">
          <button
            className="btn ghost"
            type="button"
            onClick={() => {
              setNotice(null);
              setSensorDraft((rows) => [...rows, { port: rows.length ? "B" : "A", model: "", axisCount: 3, axes: [] }]);
            }}
          >
            센서 추가
          </button>
          <button
            className="btn ghost"
            type="button"
            onClick={() => {
              setNotice(null);
              setChannelDraft((rows) => [
                ...rows,
                { channelNumber: (rows[rows.length - 1]?.channelNumber ?? 0) + 1, name: "", scale: 0.001, offset: 0 },
              ]);
            }}
          >
            채널 추가
          </button>
          <button className="btn primary" type="button" disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "저장 중" : "센서·SOH 저장"}
          </button>
        </div>
      )}
      {notice && <div className={notice.kind === "warn" ? "notice warn" : "notice"}>{notice.text}</div>}
    </div>
  );
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
  const [preview, setPreview] = useState<{ kind: "ok" | "warn"; text: string; payload?: unknown } | null>(null);

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

      {device && !device.enabled && (
        <div className="notice warn">수집이 꺼져 있다. 상태는 수집 제외다. 지금 수집은 하지 않는다.</div>
      )}

      <div className="toolbar">
        {can("operate") && device && (
          <>
            <button
              className="btn ghost"
              type="button"
              disabled={!device.enabled || pollNow.isPending}
              onClick={() => pollNow.mutate(device.id)}
            >
              지금 수집
            </button>
            <ConnectionTestControl deviceId={device.id} onResult={setTestNotice} />
            <SohPreviewControl deviceId={device.id} onResult={setPreview} />
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
      {preview && (
        <div className={preview.kind === "warn" ? "notice warn" : "notice"}>{preview.text}</div>
      )}
      {preview?.payload != null && (
        <pre className="soh-preview">{JSON.stringify(preview.payload, null, 2)}</pre>
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
                <th>수집</th>
                <td>
                  {can("configure") && device ? (
                    <CollectionToggle key={`${device.id}-enabled`} deviceId={device.id} enabled={device.enabled} />
                  ) : device?.enabled === false ? (
                    "꺼짐"
                  ) : (
                    "켜짐"
                  )}
                </td>
              </tr>
              <tr>
                <th>접속</th>
                <td>
                  {can("configure") && device ? (
                    <EndpointSettingsField
                      key={device.id}
                      deviceId={device.id}
                      endpoint={device.endpoint}
                    />
                  ) : device?.endpoint ? (
                    `${device.endpoint.scheme}://${device.endpoint.hostname}`
                  ) : (
                    "없음"
                  )}
                </td>
              </tr>
              {!(can("configure") && device) && (
                <tr>
                  <th>인증 참조</th>
                  <td>{device?.endpoint?.credentialReference ?? "없음"}</td>
                </tr>
              )}
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
      {activeTab === "settings" && device && <MetricOverridesCard deviceId={device.id} />}
      {activeTab === "settings" && device && (
        <SensorsHardwareCard
          key={`${device.id}-hardware`}
          deviceId={device.id}
          sensors={device.sensors ?? []}
          channels={device.externalSohChannels ?? []}
        />
      )}

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
