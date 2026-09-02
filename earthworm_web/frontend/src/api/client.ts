async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (body.detail && typeof body.detail === "object") {
      if (typeof body.detail.message === "string") return body.detail.message;
      if (Array.isArray(body.detail.issues)) {
        const first = body.detail.issues[0];
        return first?.message || "검증 실패";
      }
    }
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
    }
  } catch {
    /* ignore */
  }
  return `${res.status} ${res.statusText}`;
}

export class AuthError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401) throw new AuthError(await parseError(res), 401);
  if (!res.ok) throw new Error(await parseError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

let ticketInflight: Promise<string> | null = null;

async function wsTicket(): Promise<string> {
  if (!ticketInflight) {
    ticketInflight = api<{ ticket: string }>("/api/auth/ws-ticket", { method: "POST" })
      .then((d) => d.ticket)
      .finally(() => {
        ticketInflight = null;
      });
  }
  return ticketInflight;
}

export async function wsUrl(path: string, extra: Record<string, string> = {}): Promise<string> {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ticket = await wsTicket();
  const params = new URLSearchParams({ ticket, ...extra });
  return `${proto}://${location.host}${path}?${params.toString()}`;
}

export type Me = {
  id: number | null;
  username: string;
  display_name: string;
  role: "admin" | "operator" | "viewer";
  enabled?: boolean;
  is_service?: boolean;
};

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
  priority?: boolean;
  role?: string;
  fleet?: boolean;
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

export type SchemaField = {
  key: string;
  label?: string;
  required?: boolean;
  type?: string;
  unique?: string;
};

export type FamilySchema = {
  role: string;
  fleet: boolean;
  priority: boolean;
  default_ring?: string;
  label?: string;
  fields: SchemaField[];
};

export type ComposeInstance = {
  family: string;
  id: string;
  enabled: boolean;
  clone_of?: string | null;
  module_id?: string | null;
  binary_exists?: boolean;
  values: Record<string, string | number>;
  raw?: string;
};

export type ComposeBoard = {
  site: {
    heartbeat_int: number;
    default_wave_ring: string;
    log_file: string;
    installation: string;
    propagate_heartbeat: boolean;
    statmgr_enabled: boolean;
  };
  instances: ComposeInstance[];
  rings: string[];
  compose_revision: number;
  running: boolean;
};

export type ComposeIssue = {
  code: string;
  message: string;
  instance?: string | null;
  field?: string | null;
  level?: string;
};

export type Operator = {
  id: number;
  username: string;
  display_name: string;
  role: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type AuditEvent = {
  id: number;
  at: string;
  actor_username: string;
  actor_display_name: string;
  action: string;
  target: string | null;
  result: string;
  ip: string | null;
  detail: unknown;
  backup_dir: string | null;
};
