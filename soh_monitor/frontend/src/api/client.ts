// 백엔드 API 클라이언트.
// 기록계·InfluxDB 에 직접 접속하지 않는다. 모든 조회는 이 경로를 지난다.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiError(`${path} 요청이 실패했다 (HTTP ${response.status})`, response.status);
  }
  return (await response.json()) as T;
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

export interface AdapterDto {
  adapterKey: string;
  adapterVersion: string;
  manufacturer: string;
  productFamilies: string[];
  supportedModels: string[];
  protocols: string[];
  status: string;
  selectable: boolean;
}

export interface ReadinessDto {
  ready: boolean;
  environment: string;
  checks: {
    contracts?: { catalog_version?: number; metric_count?: number; error?: string };
    configuration?: { problems: string[] };
  };
}

export const api = {
  metricCatalog: () => request<MetricCatalogDto>("/api/v1/metric-catalog"),
  capabilities: () =>
    request<{ supportStates: string[]; capabilities: CapabilityDto[] }>("/api/v1/capabilities"),
  adapters: () => request<{ adapters: AdapterDto[] }>("/api/v1/adapters"),
  readiness: () => request<ReadinessDto>("/readyz"),
};
