export function defaultTimeWindow() {
  const end = new Date();
  end.setUTCMilliseconds(0);
  end.setUTCSeconds(0);
  end.setUTCMinutes(0);
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  return { start: toLocalDatetimeInput(start), end: toLocalDatetimeInput(end) };
}

export function shiftTimeWindow(start: string, end: string, deltaMs: number) {
  const s = new Date(start + "Z");
  const e = new Date(end + "Z");
  return {
    start: toLocalDatetimeInput(new Date(s.getTime() + deltaMs)),
    end: toLocalDatetimeInput(new Date(e.getTime() + deltaMs)),
  };
}

function toLocalDatetimeInput(d: Date) {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(
    d.getUTCDate()
  ).padStart(2, "0")}T${String(d.getUTCHours()).padStart(2, "0")}:${String(
    d.getUTCMinutes()
  ).padStart(2, "0")}:00`;
}

export function toIsoUtc(local: string): string {
  return new Date(local + "Z").toISOString();
}

export function channelId(t: {
  network: string;
  station: string;
  location: string;
  channel: string;
}): string {
  return `${t.network}.${t.station}.${t.location || "--"}.${t.channel}`;
}
