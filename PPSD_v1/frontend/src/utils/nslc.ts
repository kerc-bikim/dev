import type { ChannelInfo } from "../api/client";

export interface NslcQuery {
  network: string;
  station: string;
  location: string;
  channel: string;
}

const WILDCARD_RE = /[?*]/;

export function parseNslcInput(raw: string): NslcQuery | null {
  const text = raw.trim();
  if (!text) return null;
  const parts = text.split(".");
  if (parts.length > 4) return null;

  const norm = (s: string | undefined, fallback: string) =>
    (s ?? fallback).toUpperCase();

  if (parts.length === 1) {
    return {
      network: norm(parts[0], "*") || "*",
      station: "*",
      location: "*",
      channel: "*",
    };
  }
  if (parts.length === 2) {
    return {
      network: norm(parts[0], "*") || "*",
      station: norm(parts[1], "*") || "*",
      location: "*",
      channel: "*",
    };
  }
  if (parts.length === 3) {
    // NET.STA.CHA — location omitted (treated as *)
    return {
      network: norm(parts[0], "*") || "*",
      station: norm(parts[1], "*") || "*",
      location: "*",
      channel: norm(parts[2], "*") || "*",
    };
  }
  const locRaw = (parts[2] ?? "").toUpperCase();
  return {
    network: norm(parts[0], "*") || "*",
    station: norm(parts[1], "*") || "*",
    location: locRaw === "--" ? "" : locRaw,
    channel: norm(parts[3], "*") || "*",
  };
}

export function formatNslc(q: NslcQuery): string {
  return `${q.network}.${q.station}.${q.location}.${q.channel}`;
}

export function nslcHasWildcard(q: NslcQuery): boolean {
  return (
    WILDCARD_RE.test(q.network) ||
    WILDCARD_RE.test(q.station) ||
    WILDCARD_RE.test(q.location) ||
    WILDCARD_RE.test(q.channel)
  );
}

export function nslcIsCompleteExact(q: NslcQuery): boolean {
  if (nslcHasWildcard(q)) return false;
  const locLen = q.location.length;
  return (
    q.network.length >= 1 &&
    q.station.length >= 1 &&
    (locLen === 0 || locLen === 2) &&
    q.channel.length === 3
  );
}

/** Empty location → FDSN `--`. */
export function toFdsnLocation(location: string): string {
  return location === "" ? "--" : location;
}

export function channelKey(c: Pick<ChannelInfo, "network" | "station" | "location" | "channel">): string {
  return `${c.network}|${c.station}|${c.location}|${c.channel}`;
}

export function locChaKey(c: Pick<ChannelInfo, "location" | "channel">): string {
  return `${c.location}|${c.channel}`;
}

export function formatChannelLabel(c: ChannelInfo): string {
  const loc = c.location || "--";
  const rate = c.sample_rate ? ` @ ${c.sample_rate} Hz` : "";
  return `${c.network}.${c.station}.${loc}.${c.channel}${rate}`;
}

export function groupChannelsByStation(channels: ChannelInfo[]): {
  key: string;
  network: string;
  station: string;
  channels: ChannelInfo[];
}[] {
  const map = new Map<string, ChannelInfo[]>();
  for (const c of channels) {
    const key = `${c.network}|${c.station}`;
    const list = map.get(key) ?? [];
    list.push(c);
    map.set(key, list);
  }
  return [...map.entries()].map(([key, chs]) => ({
    key,
    network: chs[0].network,
    station: chs[0].station,
    channels: chs,
  }));
}
