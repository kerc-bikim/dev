import type { AppSettings, LayoutItem, LayoutPayload, SCNL } from "../types";
import { scnlKey } from "../types";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  // body가 있을 때만 JSON Content-Type — DELETE 등 빈 body + application/json 은 Fastify 400
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  const text = await res.text();
  if (!text) return {} as T;
  return JSON.parse(text) as T;
}

export const api = {
  getSettings: () => json<AppSettings>("/api/settings"),
  saveSettings: (body: Partial<AppSettings>) =>
    json<AppSettings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  getLimits: () =>
    json<{ durationMax: number; maxPanelsHard: number; memoryWarnBytes: number }>(
      "/api/settings/limits",
    ),
  testRingserver: async () => {
    const res = await fetch("/api/settings/test-ringserver", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = (await res.json().catch(() => ({}))) as {
      ok?: boolean;
      status?: number;
      target?: string;
      error?: string;
      preview?: string;
    };
    if (!res.ok || data.ok === false) {
      return {
        ok: false as const,
        status: data.status ?? res.status,
        target: data.target || "",
        error: data.error || res.statusText || `HTTP ${res.status}`,
      };
    }
    return {
      ok: true as const,
      status: data.status,
      target: data.target || "",
      error: undefined as string | undefined,
    };
  },
  listLayouts: () => json<LayoutItem[]>("/api/layouts"),
  createLayout: (name: string, payload: LayoutPayload) =>
    json<LayoutItem>("/api/layouts", {
      method: "POST",
      body: JSON.stringify({ name, payload }),
    }),
  updateLayout: (id: number, name: string, payload: LayoutPayload) =>
    json<LayoutItem>(`/api/layouts/${id}`, {
      method: "PUT",
      body: JSON.stringify({ name, payload }),
    }),
  deleteLayout: (id: number) =>
    json<{ ok: boolean }>(`/api/layouts/${id}`, { method: "DELETE" }),
  getSensitivity: async (s: SCNL) => {
    const q = new URLSearchParams({
      net: s.network,
      sta: s.station,
      loc: s.location || "--",
      cha: s.channel,
    });
    return json<{
      scnl: string;
      sensitivity: number | null;
      inputUnits: string | null;
    }>(`/api/meta/sensitivity?${q}`);
  },
};

export type StreamNode = {
  network: string;
  station: string;
  location: string;
  channel: string;
  startTime?: string;
  endTime?: string;
};

/** Parse FDSN Source ID / NSLC id into SCNL parts */
export function parseStreamId(id: string): Omit<StreamNode, "startTime" | "endTime"> | null {
  // e.g. FDSN:KG_AJD__E_L_E/MSEED  or  NET_STA_LOC_CHA  or  NET.STA.LOC.CHA
  let s = id.trim();
  s = s.replace(/^FDSN:/i, "");
  const slash = s.indexOf("/");
  if (slash >= 0) s = s.slice(0, slash);

  if (s.includes(".")) {
    const parts = s.split(".");
    if (parts.length >= 4) {
      return {
        network: parts[0] || "",
        station: parts[1] || "",
        location: parts[2] || "--",
        channel: parts.slice(3).join(".") || "",
      };
    }
  }

  // Underscore form: NET_STA_LOC_BAND_SOURCE_SUBSOURCE (location may be empty → "")
  const parts = s.split("_");
  if (parts.length >= 6) {
    const network = parts[0] || "";
    const station = parts[1] || "";
    const location = parts[2] || "--";
    const channel = `${parts[3] || ""}${parts[4] || ""}${parts[5] || ""}`;
    if (network && station && channel) {
      return { network, station, location: location || "--", channel };
    }
  }
  if (parts.length >= 4) {
    return {
      network: parts[0] || "",
      station: parts[1] || "",
      location: parts[2] || "--",
      channel: parts[3] || "",
    };
  }
  return null;
}

/** Parse ringserver /streams/json into SCNL list */
export async function fetchStreams(): Promise<StreamNode[]> {
  const res = await fetch("/ringserver/streams/json");
  if (!res.ok) throw new Error(`streams ${res.status}`);
  const data = await res.json();
  const out: StreamNode[] = [];

  const pushId = (id: string, startTime?: string, endTime?: string) => {
    const parsed = parseStreamId(id);
    if (!parsed) return;
    out.push({ ...parsed, startTime, endTime });
  };

  const pushItem = (item: unknown) => {
    if (typeof item === "string") {
      pushId(item);
      return;
    }
    if (!item || typeof item !== "object") return;
    const row = item as {
      id?: string;
      stream?: string;
      start_time?: string;
      startTime?: string;
      end_time?: string;
      endTime?: string;
    };
    const id = row.id || row.stream;
    if (id) {
      pushId(
        id,
        row.start_time || row.startTime,
        row.end_time || row.endTime,
      );
    }
  };

  if (Array.isArray(data)) {
    for (const item of data) pushItem(item);
  } else if (data && typeof data === "object") {
    // ringserver 4.x: { stream: [{ id, start_time, end_time }, ...], stream_count }
    const list = data.stream ?? data.streams;
    if (Array.isArray(list)) {
      for (const item of list) pushItem(item);
    } else {
      for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
        if (["stream", "streams", "software", "organization", "stream_count"].includes(k)) {
          continue;
        }
        const meta = v as { start_time?: string; end_time?: string };
        pushId(k, meta?.start_time, meta?.end_time);
      }
    }
  }

  const seen = new Set<string>();
  return out.filter((n) => {
    const k = scnlKey(n);
    if (!n.network || !n.station || !n.channel || seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}
