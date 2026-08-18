export type Tab = "channels" | "stations" | "networks" | "catalog" | "io" | "history";

export interface NetworkRow {
  id: number;
  code: string;
  description?: string | null;
  operator_agency?: string | null;
  restricted_status?: string | null;
}

export interface StationRow {
  id: number;
  network_id: number;
  network_code?: string | null;
  code: string;
  latitude: number;
  longitude: number;
  elevation: number;
  site_name?: string | null;
  site_description?: string | null;
  site_town?: string | null;
  site_region?: string | null;
  site_country?: string | null;
  vault?: string | null;
  geology?: string | null;
  description?: string | null;
  creation_date?: string | null;
  termination_date?: string | null;
}

export interface ChannelRow {
  id: number;
  station_id: number;
  network_code?: string;
  station_code?: string;
  site_name?: string | null;
  nslc?: string;
  location: string;
  channel: string;
  start_time: string;
  end_time?: string | null;
  sample_rate: number;
  depth: number;
  azimuth: number;
  dip: number;
  description?: string | null;
  comment?: string | null;
  channel_types?: string | null;
  clock_drift?: number | null;
  sensor_id?: string | null;
  sensor_serial?: string | null;
  sensor_type?: string | null;
  sensor_install_date?: string | null;
  sensor_remove_date?: string | null;
  datalogger_id?: string | null;
  datalogger_serial?: string | null;
  datalogger_type?: string | null;
  datalogger_install_date?: string | null;
  datalogger_remove_date?: string | null;
  has_response?: boolean;
  response_source?: string;
}

export interface CatalogRow {
  id: number;
  kind: "sensor" | "datalogger" | string;
  code: string;
  manufacturer: string;
  model: string;
  sample_rate?: number | null;
  nrl_keys?: string | null;
  origin?: "seed" | "custom" | string;
  description?: string | null;
}

export interface HistoryRow {
  id: number;
  created_at?: string | null;
  action: string;
  entity_type: string;
  entity_id?: number | null;
  source: string;
  actor?: string | null;
  nslc?: string | null;
  before_json?: string | null;
  after_json?: string | null;
  summary?: string | null;
}

export interface ResponseSeries {
  channel_id: number;
  nslc: string;
  start_time?: string | null;
  sample_rate?: number;
  amplitude: number[];
  phase_deg: number[];
  response_source?: string;
}

export interface OverlayCurve {
  output: string;
  min_freq: number;
  max_freq: number;
  npts: number;
  frequencies: number[];
  series: ResponseSeries[];
  errors: { channel_id: number; nslc: string; reason: string }[];
}

export interface SingleCurve extends ResponseSeries {
  output: string;
  input_units?: string | null;
  output_units?: string | null;
  frequencies: number[];
}

export interface ResponseStage {
  stage_sequence_number: number;
  type: string;
  editable: boolean;
  input_units?: string | null;
  output_units?: string | null;
  pz_transfer_function_type?: string;
  normalization_frequency?: number;
  normalization_factor?: number;
  stage_gain?: number;
  stage_gain_frequency?: number;
  poles?: { real: number; imag: number }[];
  zeros?: { real: number; imag: number }[];
}

export interface ResponseStages {
  channel_id: number;
  nslc: string;
  response_source?: string;
  stages: ResponseStage[];
  warnings?: string[];
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") {
      if (Array.isArray(data.errors) && data.errors.length) {
        const extra = data.errors
          .map((item: { reason?: string }) => item.reason)
          .filter(Boolean)
          .join("\n");
        return extra ? `${data.detail}\n${extra}` : data.detail;
      }
      return data.detail;
    }
    return JSON.stringify(data.detail);
  } catch {
    return res.statusText;
  }
}

function apiKeyHeader(): Record<string, string> {
  const key = localStorage.getItem("sxm-api-key") || "";
  return key ? { "X-API-Key": key } : {};
}

function actorQuery(actor: string): string {
  const name = actor.trim();
  return name ? `?actor=${encodeURIComponent(name)}` : "";
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: apiKeyHeader() });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function apiSend<T>(
  method: string,
  path: string,
  body?: unknown,
  actor = ""
): Promise<T> {
  const res = await fetch(`${path}${actorQuery(actor)}`, {
    method,
    headers: {
      ...apiKeyHeader(),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function uploadFile(
  file: File,
  replaceAll: boolean,
  actor: string
): Promise<{ created: number; updated: number; warnings: string[] }> {
  const form = new FormData();
  form.append("file", file);
  form.append("replace_all", replaceAll ? "true" : "false");
  form.append("confirm_replace", replaceAll ? "true" : "false");
  if (actor.trim()) form.append("actor", actor.trim());
  const res = await fetch("/api/import", {
    method: "POST",
    headers: apiKeyHeader(),
    body: form,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

function parseExportWarnings(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export async function downloadFile(path: string, filename: string): Promise<string[]> {
  const res = await fetch(path, { headers: apiKeyHeader() });
  if (!res.ok) throw new Error(await parseError(res));
  const warnings = parseExportWarnings(res.headers.get("X-Export-Warnings"));
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return warnings;
}
