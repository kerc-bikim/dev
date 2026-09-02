/** Canonical copy: keep in sync with shared/bandPassPresets.ts (backend tsc rootDir=src). */

export type BandPassGroup = "builtin" | "custom";

export type BandPassPreset = {
  id: string;
  name: string;
  fminHz: number;
  fmaxHz: number;
  group: BandPassGroup;
  builtin?: boolean;
};

export const BUILTIN_BANDPASS_PRESETS: BandPassPreset[] = [
  {
    id: "infra-0.02-0.5",
    name: "BP 0.02–0.5 Hz",
    fminHz: 0.02,
    fmaxHz: 0.5,
    group: "builtin",
    builtin: true,
  },
  {
    id: "seis-0.1-1",
    name: "BP 0.1–1 Hz",
    fminHz: 0.1,
    fmaxHz: 1.0,
    group: "builtin",
    builtin: true,
  },
  {
    id: "infra-0.5-5",
    name: "BP 0.5–5 Hz",
    fminHz: 0.5,
    fmaxHz: 5.0,
    group: "builtin",
    builtin: true,
  },
  {
    id: "seis-1-5",
    name: "BP 1–5 Hz",
    fminHz: 1.0,
    fmaxHz: 5.0,
    group: "builtin",
    builtin: true,
  },
  {
    id: "seis-1-10",
    name: "BP 1–10 Hz",
    fminHz: 1.0,
    fmaxHz: 10.0,
    group: "builtin",
    builtin: true,
  },
];

const REMOVED_PRESET_ALIASES: Record<string, string> = {
  "infra-1-10": "seis-1-10",
};

export function remapBandPassPresetId(id: string | null | undefined): string | null {
  if (!id) return null;
  return REMOVED_PRESET_ALIASES[id] || id;
}

function compareByBand(a: BandPassPreset, b: BandPassPreset): number {
  if (a.fminHz !== b.fminHz) return a.fminHz - b.fminHz;
  return a.fmaxHz - b.fmaxHz;
}

export function mergeBandPassPresets(
  stored: BandPassPreset[] | undefined | null,
): BandPassPreset[] {
  const custom = (stored || []).filter(
    (p) => p && p.group === "custom" && typeof p.id === "string" && p.id,
  );
  const byId = new Map<string, BandPassPreset>();
  for (const b of BUILTIN_BANDPASS_PRESETS) byId.set(b.id, { ...b, builtin: true });
  for (const c of custom) {
    if (byId.has(c.id) && byId.get(c.id)!.builtin) continue;
    const fmin = Number(c.fminHz);
    const fmax = Number(c.fmaxHz);
    if (!(fmin > 0) || !(fmax > fmin) || fmax > 1e6) continue;
    byId.set(c.id, {
      id: c.id,
      name: String(c.name || c.id).slice(0, 64),
      fminHz: fmin,
      fmaxHz: fmax,
      group: "custom",
      builtin: false,
    });
  }
  const builtin = [...byId.values()].filter((p) => p.builtin).sort(compareByBand);
  const extras = [...byId.values()].filter((p) => !p.builtin).sort(compareByBand);
  return [...builtin, ...extras];
}

export function sanitizeBandPassPresets(list: unknown): BandPassPreset[] | undefined {
  if (!Array.isArray(list)) return undefined;
  const out: BandPassPreset[] = [];
  for (const raw of list) {
    if (!raw || typeof raw !== "object") continue;
    const p = raw as Record<string, unknown>;
    const id = typeof p.id === "string" ? p.id.trim() : "";
    if (!id) continue;
    const group = p.group === "custom" ? "custom" : "builtin";
    const fmin = Number(p.fminHz);
    const fmax = Number(p.fmaxHz);
    if (!(fmin > 0) || !(fmax > fmin) || fmax > 1e6) continue;
    if (group !== "custom") {
      const b = BUILTIN_BANDPASS_PRESETS.find((x) => x.id === id);
      if (b) {
        out.push({ ...b, builtin: true });
        continue;
      }
    }
    out.push({
      id,
      name: String(p.name || id).slice(0, 64),
      fminHz: fmin,
      fmaxHz: fmax,
      group: "custom",
      builtin: false,
    });
  }
  return mergeBandPassPresets(out);
}

export function resolveBandPass(
  enabled: boolean | undefined,
  presetId: string | null | undefined,
  presets: BandPassPreset[] | undefined,
): { fminHz: number; fmaxHz: number } | null {
  if (!enabled || !presetId) return null;
  const list = presets?.length ? presets : BUILTIN_BANDPASS_PRESETS;
  const p = list.find((x) => x.id === remapBandPassPresetId(presetId));
  if (!p || !(p.fminHz > 0) || !(p.fmaxHz > p.fminHz)) return null;
  return { fminHz: p.fminHz, fmaxHz: p.fmaxHz };
}

export function clampBandPassToNyquist(
  fminHz: number,
  fmaxHz: number,
  sampleRate: number,
): { fminHz: number; fmaxHz: number; clamped: boolean } | null {
  if (!(sampleRate > 0) || !(fminHz > 0) || !(fmaxHz > fminHz)) return null;
  const nyq = sampleRate / 2;
  const loMin = nyq * 1e-6;
  const hiMax = nyq * 0.999;
  let lo = Math.max(fminHz, loMin);
  let hi = Math.min(fmaxHz, hiMax);
  const clamped = lo !== fminHz || hi !== fmaxHz;
  if (!(lo < hi)) return null;
  return { fminHz: lo, fmaxHz: hi, clamped };
}
