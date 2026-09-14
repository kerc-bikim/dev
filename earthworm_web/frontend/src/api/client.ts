export type ComposeIssue = {
  code: string;
  message: string;
  instance?: string | null;
  field?: string | null;
  level?: string;
};

type ErrorBody = { message: string; issues?: ComposeIssue[] };

async function parseError(res: Response): Promise<ErrorBody> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return { message: body.detail };
    if (body.detail && typeof body.detail === "object") {
      const issues = Array.isArray(body.detail.issues) ? (body.detail.issues as ComposeIssue[]) : undefined;
      let message = typeof body.detail.message === "string" ? body.detail.message : "";
      if (issues?.length && (!message || message === "검증 실패")) {
        const errs = issues.filter((i) => i.level !== "warning");
        const parts = (errs.length ? errs : issues).map((i) => i.message).filter(Boolean).slice(0, 3);
        if (parts.length) message = parts.join("; ");
      }
      return { message: message || "요청이 거절되었습니다", issues };
    }
    if (Array.isArray(body.detail)) {
      return { message: body.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ") };
    }
  } catch {
    /* ignore */
  }
  return { message: `${res.status} ${res.statusText}` };
}

export class ApiError extends Error {
  status: number;
  issues?: ComposeIssue[];
  constructor(message: string, status: number, issues?: ComposeIssue[]) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

export class AuthError extends ApiError {
  constructor(message: string, status: number) {
    super(message, status);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (res.status === 401) {
    const err = await parseError(res);
    throw new AuthError(err.message, 401);
  }
  if (!res.ok) {
    const err = await parseError(res);
    throw new ApiError(err.message, res.status, err.issues);
  }
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
