export const API_KEY = import.meta.env.VITE_API_KEY ?? "dev";

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
    }
  } catch {
    /* ignore */
  }
  return `${res.status} ${res.statusText}`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-API-Key", API_KEY);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) throw new Error(await parseError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function wsUrl(path: string, extra: Record<string, string> = {}): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({ key: API_KEY, ...extra });
  return `${proto}://${location.host}${path}?${params.toString()}`;
}

export type RingRow = {
  name: string;
  key: number;
  size: number;
  in_startstop: boolean;
};

export type Check = { name: string; ok: boolean; detail?: string };

export type ModuleRow = {
  id: string;
  binary: string;
  binary_exists: boolean;
  param_file: string | null;
  desc_file: string | null;
  module_id: string | null;
  enabled: boolean;
  clone_of?: string | null;
  restart_me?: boolean;
  locked?: boolean;
  has_descriptor?: boolean;
  pid?: number | null;
  process?: string;
  heartbeat?: string;
  health?: string;
  argument?: string;
};

export type Dashboard = {
  running: boolean;
  startstop: { alive: boolean; pid: number | null; status: string };
  hostname_os: string;
  version: string;
  disk_kb: number | null;
  rings: { name: string; key: string; size_kib: number }[];
  log_dir: string;
  params_dir: string;
  modules: ModuleRow[];
  error?: string | null;
};
