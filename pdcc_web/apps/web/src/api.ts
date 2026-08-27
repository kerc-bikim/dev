export type Me = { username: string; role: string };
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
  azimuth: number | null;
  dip: number | null;
  sample_rate: number | null;
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
};

export async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as {
      detail?: string | { message?: string };
    };
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
  if (!response.ok) throw new Error(await readError(response));
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

export function apiPostResponse(path: string, body?: unknown): Promise<Response> {
  return fetch(path, {
    method: "POST",
    credentials: "include",
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

export type ExportLoss = {
  nslc: string;
  field: string;
  kind: string;
  original?: string;
  result?: string;
  reason: string;
};

export type ExportPreview = {
  kind: string;
  channel_count: number;
  errors: ExportLoss[];
  losses: ExportLoss[];
  drops: ExportLoss[];
  needs_confirm: boolean;
  blocked: boolean;
};

export type ExportJob = {
  id: string;
  project_id: number;
  username: string;
  kind: string;
  scope: string;
  station: string | null;
  start_time: string | null;
  nslc: string | null;
  status: string;
  progress: number;
  message: string;
  error: string | null;
  filename: string | null;
  media_type: string | null;
  downloadable: boolean;
  warnings: string[];
  losses: ExportLoss[];
  drops: ExportLoss[];
  created_at: string | null;
};

export async function parseExportError(
  response: Response
): Promise<{ message: string; preview?: Partial<ExportPreview> }> {
  try {
    const body = (await response.json()) as {
      detail?:
        | string
        | {
            message?: string;
            errors?: ExportLoss[];
            losses?: ExportLoss[];
            drops?: ExportLoss[];
          };
    };
    if (typeof body.detail === "string") return { message: body.detail };
    if (body.detail && typeof body.detail === "object") {
      return {
        message: body.detail.message || `요청 실패 (${response.status})`,
        preview: {
          errors: body.detail.errors || [],
          losses: body.detail.losses || [],
          drops: body.detail.drops || [],
          needs_confirm: Boolean(body.detail.losses?.length),
          blocked: Boolean(body.detail.errors?.length),
        },
      };
    }
  } catch {
    /* ignore */
  }
  return { message: `요청 실패 (${response.status})` };
}

export async function apiDownload(path: string, fallbackName: string): Promise<void> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) throw new Error(await readError(response));
  const blob = await response.blob();
  const header = response.headers.get("content-disposition") || "";
  const match = /filename="([^"]+)"/.exec(header);
  const name = match?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
