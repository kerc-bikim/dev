export type Me = {
  username: string;
  role: string;
  display_name?: string;
  active?: boolean;
  org_id?: number | null;
  org_name?: string | null;
};
export type Health = { ok: boolean; db: boolean; redis: boolean };
export type WizardQuestion = { key: string; question: string; options: string[] };
export type WizardMatch = {
  instconfig: string;
  description: string;
  parameters: Record<string, string>;
};
export type WizardResult = {
  element: string;
  manufacturer: string;
  model: string;
  answers: Record<string, string>;
  questions: WizardQuestion[];
  locked: Record<string, string>;
  matches: WizardMatch[];
  match_count: number;
};
export type ResponseCurve = {
  instconfig: string | null;
  output: string;
  input_units: string | null;
  output_units: string | null;
  sample_rate: number;
  frequencies: number[];
  amplitude: number[];
  phase_deg: number[];
  min_freq: number;
  max_freq: number;
  npts: number;
};
export type ChannelSummary = {
  location: string;
  code: string;
  start: string | null;
  end: string | null;
  latitude?: number | null;
  longitude?: number | null;
  elevation?: number | null;
  depth?: number | null;
  azimuth: number | null;
  dip: number | null;
  sample_rate: number | null;
  sensitivity?: number | null;
  has_response: boolean;
  nslc: string;
};
export type LockInfo = {
  station_path: string;
  username: string;
  user_id?: number;
  expires_at?: string;
  mine?: boolean | null;
};
export type StationSummary = {
  code: string;
  start: string;
  end: string | null;
  site_name: string | null;
  latitude: number | null;
  longitude: number | null;
  elevation: number | null;
  station_path: string;
  channels: ChannelSummary[];
  lock?: LockInfo | null;
};
export type Project = {
  id: number;
  name: string;
  network_code: string;
  operator: string | null;
  status: string;
  updated_at: string | null;
  station_count: number;
  channel_count: number;
  stations: StationSummary[];
  nrl_applied: boolean;
  lock?: LockInfo | null;
  can_undo?: boolean;
  draft?: { updated_at: string | null; base_updated_at: string; conflict: boolean } | null;
  has_original?: boolean;
  my_role?: string | null;
  can_edit?: boolean;
};
export type EquipmentSet = {
  id: number;
  name: string;
  notes: string;
  sensor_instconfig: string;
  datalogger_instconfig: string;
  channels: string[];
  nrl_version: string;
  stale: boolean;
};
export type VersionInfo = {
  id: number;
  number: number;
  actor: string;
  action: string;
  summary: string;
  created_at: string | null;
};
export type FieldDiff = { path: string; a?: string; b?: string; server?: string; mine?: string };
export type ValidationIssue = {
  code: string;
  message: string;
  path: string;
  field: string;
  station: string | null;
  start: string | null;
  nslc: string | null;
  level?: "error" | "warning";
  source?: string;
  official?: string | null;
};
export type ValidateResult = {
  issues: ValidationIssue[];
  source: string;
  mode: string;
  error_count: number;
  warning_count: number;
  can_export_seed: boolean;
  filename: string;
  engine?: string;
};
export type NrlSearchHit = {
  element: string;
  manufacturer: string;
  model: string | null;
  via: string;
};
export type OrgInfo = {
  id: number;
  name: string;
  user_count: number;
  created_at: string | null;
};
export type UserInfo = {
  id: number;
  username: string;
  display_name: string;
  role: string;
  active: boolean;
  org_id: number | null;
  org_name: string | null;
  created_at: string | null;
};
export type MemberInfo = {
  user_id: number;
  username: string;
  display_name: string;
  role: string;
  active: boolean;
};
  mode: string;
  source?: string;
  badge?: string;
  base_url: string;
  cache_ttl_sec: number;
  last_ok: boolean;
  last_ok_at?: string | null;
  cache_count?: number;
};

export class ApiError extends Error {
  status: number;
  payload: unknown;
  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

export async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string | { message?: string } };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail && typeof body.detail === "object" && body.detail.message) {
      return body.detail.message;
    }
  } catch {
    /* ignore */
  }
  return `요청 실패 (${response.status})`;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  if (!response.ok) {
    let payload: unknown = null;
    let message = `요청 실패 (${response.status})`;
    try {
      payload = await response.json();
      const detail = (payload as { detail?: string | { message?: string } }).detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object" && detail.message) message = detail.message;
    } catch {
      /* ignore */
    }
    throw new ApiError(message, response.status, payload);
  }
  return (await response.json()) as T;
}

export const apiGet = api;

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, {
    method: "PUT",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function apiDelete<T>(path: string): Promise<T> {
  return api<T>(path, { method: "DELETE" });
}

export async function apiText(path: string): Promise<string> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) throw new Error(await readError(response));
  return response.text();
}

export async function apiDownload(
  path: string
): Promise<{ filename: string; blob: Blob }> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) throw new Error(await readError(response));
  const header = response.headers.get("X-PDCC-Filename") || "";
  const disp = response.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disp);
  const filename = header || match?.[1] || "download.bin";
  return { filename, blob: await response.blob() };
}
