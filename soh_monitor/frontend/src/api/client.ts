// 백엔드 API 클라이언트.
// 기록계·InfluxDB 에 직접 접속하지 않는다. 모든 조회는 이 경로를 지난다.
// 세션 쿠키를 보내야 하므로 credentials: "include" 를 기본으로 둔다.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function readErrorMessage(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : String(item)))
        .join("; ");
    }
  }
  return `${response.url} 요청이 실패했다 (HTTP ${response.status})`;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    if (
      response.status === 401 &&
      !path.includes("/api/v1/auth/login") &&
      !path.includes("/api/v1/auth/me")
    ) {
      window.dispatchEvent(new CustomEvent("soh:session-expired"));
    }
    throw new ApiError(await readErrorMessage(response), response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export type Role = "ADMIN" | "OPERATOR" | "VIEWER";

export interface UserDto {
  id: string;
  username: string;
  displayName: string;
  email: string | null;
  role: Role;
  enabled: boolean;
  mustChangePassword: boolean;
  lastLoginAt: string | null;
}

export interface MetricDefinitionDto {
  key: string;
  category: string;
  displayName: string;
  valueType: string;
  unit: string | null;
  source: string;
  measurement: string;
  field: string;
  required: boolean;
  aggregation: string;
  dimensions: string[];
  capability: string | null;
  description: string;
}

export interface MetricCatalogDto {
  version: number;
  statuses: string[];
  dimensions: string[];
  categories: { key: string; displayName: string; order: number }[];
  metrics: MetricDefinitionDto[];
}

export interface CapabilityDto {
  key: string;
  displayName: string;
  detectable: boolean;
  dimension: string | null;
  description: string;
}

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  enum?: (string | number)[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minLength?: number;
}

export interface AdapterDto {
  adapterKey: string;
  adapterVersion: string;
  manufacturer: string;
  productFamilies: string[];
  generation?: string | null;
  supportedModels: string[];
  protocols: string[];
  capabilities?: string[];
  status: string;
  selectable: boolean;
  configurationSchema?: {
    type?: string;
    properties?: Record<string, JsonSchemaProperty>;
    required?: string[];
    secretFields?: string[];
  };
  uiHints?: {
    groups?: { title: string; fields: string[] }[];
    notes?: string[];
  };
}

export interface ReadinessDto {
  ready: boolean;
  environment: string;
  checks: {
    contracts?: { catalog_version?: number; metric_count?: number; error?: string };
    configuration?: { problems: string[] };
  };
}

export interface StationDto {
  id: string;
  networkCode: string;
  stationCode: string;
  name: string;
  regionId: string | null;
  latitude: number | null;
  longitude: number | null;
  elevationM: number | null;
  address: string | null;
  timezone: string;
  operatorName: string | null;
  operatorContact: string | null;
  powerProfile: string | null;
  status: string;
  notes: string | null;
  deviceCount: number;
  worstSeverity: string | null;
  categories: Record<string, string>;
    lastSuccessAt: string | null;
  collectionMode: string | null;
  edgeUnreachable?: boolean;
}

export interface EndpointDto {
  scheme: string;
  hostname: string;
  port: number | null;
  basePath: string;
  tlsVerify: boolean;
  credentialReference: string | null;
  connectTimeoutMs: number;
  requestTimeoutMs: number;
  connectionOptions: Record<string, unknown>;
}

export interface SensorAxisDto {
  id?: string;
  axisCode: string;
  sohChannel: string | null;
  warningThreshold: number | null;
  criticalThreshold: number | null;
  unit: string;
}

export interface SensorDto {
  id?: string;
  port: string;
  manufacturer: string | null;
  model: string | null;
  serialNumber: string | null;
  axisCount: number;
  enabled: boolean;
  axes: SensorAxisDto[];
}

export interface ExternalSohDto {
  id?: string;
  channelNumber: number;
  name: string;
  measurementType: string;
  rawUnit: string;
  outputUnit: string;
  scale: number;
  offset: number;
  warningLow: number | null;
  warningHigh: number | null;
  criticalLow: number | null;
  criticalHigh: number | null;
  enabled: boolean;
  formula?: string;
}

export interface DeviceDto {
  id: string;
  stationId: string;
  label: string;
  serialNumber: string | null;
  instrumentId: string | null;
  firmwareVersion: string | null;
  adapterKey: string;
  adapterVersion: string | null;
  collectionMode: string;
  edgeId: string | null;
  collectionProfileId: string | null;
  metricProfileId: string | null;
  dataSourceUri: string | null;
  enabled: boolean;
  status: string;
  notes: string | null;
  endpoint: EndpointDto | null;
  sensors?: SensorDto[];
  externalSohChannels?: ExternalSohDto[];
}

export interface IdentityDto {
  manufacturer: string | null;
  model: string | null;
  serialNumber: string | null;
  instrumentId: string | null;
  firmwareVersion: string | null;
  channelCount: number | null;
  sensorPorts: string[];
  externalSohChannels: number | null;
}

export interface ConnectionTestDto {
  reachable?: boolean;
  latencyMs?: number | null;
  httpStatus?: number | null;
  message: string;
  identity?: IdentityDto | null;
  queued?: boolean;
  taskId?: string;
  edgeId?: string;
}

export interface FleetSummaryDto {
  deviceCount: number;
  connectivity: Record<string, number>;
  openIncidents: number;
  staleStates: number;
  byCategory: Record<string, Record<string, number>>;
}

export interface IncidentDto {
  incidentId: string;
  deviceId: string | null;
  stationCode: string | null;
  category: string;
  metricKey: string | null;
  dimension: string | null;
  severity: string;
  status: string;
  title: string;
  firstObservedAt: string | null;
  lastObservedAt: string | null;
  resolvedAt: string | null;
  acknowledgedAt: string | null;
  acknowledgedBy: string | null;
  worstValue: number | null;
  thresholdValue: number | null;
  maintenanceRelated: boolean;
  suppressedByEdge: boolean;
  edgeId?: string | null;
  detail: Record<string, unknown>;
}

export interface MaintenanceWindowDto {
  id: string;
  scope: string;
  scopeId: string | null;
  startsAt: string | null;
  endsAt: string | null;
  reason: string | null;
  suppressAlerts: boolean;
}

export interface HealthMetricDto {
  metricKey: string;
  category: string;
  dimension: string | null;
  severity: string;
  supportState: string;
  value: string | null;
  isStale: boolean;
  observedAt: string | null;
  detail: Record<string, unknown>;
}

export interface DeviceHealthDto {
  deviceId: string;
  stationCode: string | null;
  overall: string;
  lastSuccessAt: string | null;
  lastPollAt: string | null;
  consecutiveFailures: number;
  categories: Record<string, { severity: string; isStale: boolean; evaluatedAt: string | null; detail: Record<string, unknown> }>;
  metrics: HealthMetricDto[];
}

export interface CollectionProfileDto {
  id: string;
  name: string;
  description: string | null;
  pollIntervalMinutes: number;
  retryCount: number;
  retryDelaySeconds: number;
  dataCheckIntervalMinutes: number;
  connectTimeoutMs: number;
  requestTimeoutMs: number;
  isDefault: boolean;
  affectedDeviceCount: number;
}

export interface MetricOverrideDto {
  id?: string;
  metricKey: string;
  dimensionValue: string | null;
  enabled: boolean | null;
  alertingEnabled: boolean | null;
  warningCondition: Record<string, unknown> | null;
  criticalCondition: Record<string, unknown> | null;
  holdSeconds: number | null;
  recoverySeconds: number | null;
  reason: string | null;
}

export interface ProfileMetricDto {
  metricKey: string;
  enabled: boolean;
  alertingEnabled: boolean;
  warningCondition: Record<string, unknown>;
  criticalCondition: Record<string, unknown>;
  holdSeconds: number;
  recoverySeconds: number;
  consecutiveViolations: number;
}

export interface MetricProfileDto {
  id: string;
  name: string;
  description: string | null;
  isDefault: boolean;
  affectedDeviceCount: number;
  entries: ProfileMetricDto[];
}

export interface AuditLogDto {
  id: string;
  occurredAt: string | null;
  actorId: string | null;
  actorName: string | null;
  action: string;
  entityType: string;
  entityId: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  sourceIp: string | null;
}

export interface PollRunDto {
  pollId: string;
  observedAt: string | null;
  receivedAt?: string | null;
  success: boolean;
  latencyMs: number | null;
  httpStatus?: number | null;
  sampleCount: number;
  errorCode: string | null;
  errorMessage: string | null;
}

export interface EdgeHealthDto {
  connectivityStatus: string;
  configStatus: string;
  collectorStatus: string;
  spoolStatus: string;
  certificateStatus: string;
  clockStatus: string;
  pendingBatches: number | null;
  oldestPendingAgeSeconds: number | null;
  clockOffsetMs: number | null;
  detail: Record<string, unknown>;
}

export interface EdgeAssignmentDto {
  id: string;
  deviceId: string;
  assignmentEpoch: number;
  role: string;
  enabled: boolean;
  assignedAt: string | null;
  adapterKey?: string | null;
  label?: string | null;
  stationId?: string | null;
  stationCode?: string | null;
}

export interface EdgeDto {
  id: string;
  edgeCode: string;
  name: string;
  regionId: string | null;
  status: string;
  softwareVersion: string | null;
  installedAdapters: Record<string, unknown>;
  certificateExpiresAt: string | null;
  certificateSerial?: string | null;
  lastHeartbeatAt: string | null;
  lastUploadAt: string | null;
  lastConfigVersion: number;
  lastConfigAppliedVersion: number;
  spoolUsedBytes: number | null;
  spoolLimitBytes: number | null;
  ipAddress: string | null;
  registeredAt: string | null;
  revokedAt?: string | null;
  notes: string | null;
  hasEnrollmentToken: boolean;
  enrollmentToken?: string;
  enrollmentTokenExpiresAt?: string | null;
  health?: EdgeHealthDto;
  assignments?: EdgeAssignmentDto[];
}

export interface TopologyStationDto {
  id: string;
  stationCode: string;
  networkCode: string;
  name: string;
  worstSeverity: string | null;
  edgeUnreachable: boolean;
  collectionMode: string | null;
}

export interface TopologyEdgeDto {
  id: string;
  edgeCode: string;
  name: string;
  status: string;
  softwareVersion: string | null;
  lastHeartbeatAt: string | null;
  stations: TopologyStationDto[];
}

export interface TopologyRegionDto {
  id: string;
  regionCode: string;
  name: string;
  edges: TopologyEdgeDto[];
  stationsWithoutEdge: TopologyStationDto[];
}

export interface FleetTopologyDto {
  regions: TopologyRegionDto[];
  unassigned: { edges: TopologyEdgeDto[]; stations: TopologyStationDto[] };
}

export const api = {
  metricCatalog: () => request<MetricCatalogDto>("/api/v1/metric-catalog"),
  capabilities: () =>
    request<{ supportStates: string[]; capabilities: CapabilityDto[] }>("/api/v1/capabilities"),
  adapters: () => request<{ adapters: AdapterDto[] }>("/api/v1/adapters"),
  readiness: () => request<ReadinessDto>("/readyz"),

  login: (username: string, password: string) =>
    request<{ user: UserDto }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" }),
  me: () => request<{ user: UserDto }>("/api/v1/auth/me"),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ user: UserDto }>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ currentPassword, newPassword }),
    }),

  stations: (params?: { status?: string; q?: string }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.q) query.set("q", params.q);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ stations: StationDto[] }>(`/api/v1/stations${suffix}`);
  },
  station: (id: string) =>
    request<{ station: StationDto; devices: DeviceDto[] }>(`/api/v1/stations/${id}`),
  createStation: (body: Record<string, unknown>) =>
    request<{ station: StationDto }>("/api/v1/stations", { method: "POST", body: JSON.stringify(body) }),
  updateStation: (id: string, body: Record<string, unknown>) =>
    request<{ station: StationDto }>(`/api/v1/stations/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  retireStation: (id: string) =>
    request<{ station: StationDto }>(`/api/v1/stations/${id}/retire`, { method: "POST" }),
  stationHealth: (id: string) =>
    request<{
      stationId: string;
      stationCode: string;
      overall: string;
      devices: {
        deviceId: string;
        label: string;
        enabled: boolean;
        status: string;
        overall: string;
        lastSuccessAt: string | null;
        consecutiveFailures: number;
      }[];
    }>(`/api/v1/stations/${id}/current-health`),
  importStations: (file: File) => {
    const data = new FormData();
    data.append("file", file);
    return request<{
      imported: number;
      failed: number;
      stations: Record<string, unknown>[];
      errors: { row: number; field: string | null; message: string }[];
    }>("/api/v1/stations/import", { method: "POST", body: data });
  },

  createDevice: (stationId: string, body: Record<string, unknown>) =>
    request<{ device: DeviceDto }>(`/api/v1/stations/${stationId}/devices`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  device: (id: string) => request<{ device: DeviceDto }>(`/api/v1/devices/${id}`),
  updateDevice: (id: string, body: Record<string, unknown>) =>
    request<{ device: DeviceDto }>(`/api/v1/devices/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  retireDevice: (id: string) => request<{ device: DeviceDto }>(`/api/v1/devices/${id}/retire`, { method: "POST" }),
  replaceSensors: (deviceId: string, body: Record<string, unknown>[]) =>
    request<{ sensors: SensorDto[] }>(`/api/v1/devices/${deviceId}/sensors`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  replaceExternalSoh: (deviceId: string, body: Record<string, unknown>[]) =>
    request<{ channels: ExternalSohDto[] }>(`/api/v1/devices/${deviceId}/external-soh-channels`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  testConnection: (body: Record<string, unknown>, signal?: AbortSignal) =>
    request<ConnectionTestDto>("/api/v1/devices/test-connection", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
  testDeviceConnection: (deviceId: string, signal?: AbortSignal) =>
    request<ConnectionTestDto>(`/api/v1/devices/${deviceId}/test-connection`, {
      method: "POST",
      signal,
    }),
  probe: (body: Record<string, unknown>, signal?: AbortSignal) =>
    request<{ identity: IdentityDto }>("/api/v1/devices/probe", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
  sohPreview: (deviceId: string) =>
    request<{ success: boolean; payload: unknown; errorMessage: string | null }>(
      `/api/v1/devices/${deviceId}/soh-preview`,
    ),
  pollNow: (deviceId: string) =>
    request<{ accepted: boolean }>(`/api/v1/devices/${deviceId}/poll-now`, { method: "POST" }),
  pollRuns: (deviceId: string) =>
    request<{ runtime: Record<string, unknown>; runs: PollRunDto[] }>(`/api/v1/devices/${deviceId}/poll-runs`),
  deviceHealth: (deviceId: string) => request<DeviceHealthDto>(`/api/v1/devices/${deviceId}/current-health`),
  deviceCapabilities: (deviceId: string) =>
    request<{
      deviceId: string;
      capabilities: { key: string; dimension: string | null; supportState: string }[];
    }>(`/api/v1/devices/${deviceId}/capabilities`),
  deviceOverrides: (deviceId: string) =>
    request<{ overrides: MetricOverrideDto[] }>(`/api/v1/devices/${deviceId}/metric-overrides`),
  replaceDeviceOverrides: (deviceId: string, body: Record<string, unknown>[]) =>
    request<{ overrides: MetricOverrideDto[] }>(`/api/v1/devices/${deviceId}/metric-overrides`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  fleetSummary: () => request<FleetSummaryDto>("/api/v1/fleet/summary"),
  fleetTopology: () => request<FleetTopologyDto>("/api/v1/fleet/topology"),
  incidents: (status = "open") =>
    request<{ incidents: IncidentDto[] }>(`/api/v1/incidents?status=${encodeURIComponent(status)}`),
  acknowledgeIncident: (id: string, message = "") =>
    request<{ incidentId: string; status: string }>(
      `/api/v1/incidents/${id}/acknowledge?message=${encodeURIComponent(message)}`,
      { method: "POST" },
    ),
  maintenanceWindows: (params?: { scope?: string; scopeId?: string; active?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.scope) query.set("scope", params.scope);
    if (params?.scopeId) query.set("scopeId", params.scopeId);
    if (params?.active) query.set("active", "true");
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ windows: MaintenanceWindowDto[] }>(`/api/v1/maintenance-windows${suffix}`);
  },
  createMaintenanceWindow: (body: Record<string, unknown>) =>
    request<{ window: MaintenanceWindowDto }>("/api/v1/maintenance-windows", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  closeMaintenanceWindow: (id: string) =>
    request<{ window: MaintenanceWindowDto }>(`/api/v1/maintenance-windows/${id}/close`, { method: "POST" }),

  incidentEvents: (id: string) =>
    request<{
      incidentId: string;
      title: string;
      events: { occurredAt: string; eventType: string; message: string | null; actorName: string | null }[];
    }>(`/api/v1/incidents/${id}/events`),

  collectionProfiles: () => request<{ profiles: CollectionProfileDto[] }>("/api/v1/collection-profiles"),
  metricProfiles: () => request<{ profiles: MetricProfileDto[] }>("/api/v1/metric-profiles"),
  metricProfile: (id: string) => request<{ profile: MetricProfileDto }>(`/api/v1/metric-profiles/${id}`),
  createMetricProfile: (body: Record<string, unknown>) =>
    request<{ profile: MetricProfileDto }>("/api/v1/metric-profiles", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateMetricProfile: (id: string, body: Record<string, unknown>) =>
    request<{ profile: MetricProfileDto }>(`/api/v1/metric-profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  updateCollectionProfile: (id: string, body: Record<string, unknown>) =>
    request<{ profile: CollectionProfileDto }>(`/api/v1/collection-profiles/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  users: () => request<{ users: UserDto[] }>("/api/v1/users"),
  createUser: (body: Record<string, unknown>) =>
    request<{ user: UserDto }>("/api/v1/users", { method: "POST", body: JSON.stringify(body) }),
  auditLogs: () => request<{ logs: AuditLogDto[] }>("/api/v1/audit-logs?limit=100"),

  regions: () =>
    request<{ regions: { id: string; regionCode: string; name: string }[] }>("/api/v1/regions"),
  edges: () => request<{ edges: EdgeDto[] }>("/api/v1/edges"),
  edge: (id: string) => request<{ edge: EdgeDto }>(`/api/v1/edges/${id}`),
  createEdge: (body: Record<string, unknown>) =>
    request<{ edge: EdgeDto }>("/api/v1/edges", { method: "POST", body: JSON.stringify(body) }),
  reissueEnrollment: (id: string) =>
    request<{ enrollmentToken: string; enrollmentTokenExpiresAt: string | null }>(
      `/api/v1/edges/${id}/enrollment-token`,
      { method: "POST" },
    ),
  revokeEdge: (id: string) =>
    request<{ edge: EdgeDto }>(`/api/v1/edges/${id}/revoke`, { method: "POST" }),
  assignDevice: (edgeId: string, deviceId: string) =>
    request<{ assignment: Record<string, unknown> }>(`/api/v1/edges/${edgeId}/assignments`, {
      method: "POST",
      body: JSON.stringify({ deviceId }),
    }),
  unassignDevice: (edgeId: string, deviceId: string) =>
    request<{ ok: boolean }>(`/api/v1/edges/${edgeId}/assignments/${deviceId}`, { method: "DELETE" }),
};
