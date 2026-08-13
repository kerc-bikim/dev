import type { YAxisType } from "../api/client";

/** Must match backend YAXIS_DEFAULT_LIMITS in yaxis_units.py */
export const YAXIS_DEFAULT_LIMITS: Record<
  YAxisType,
  { y_min: number; y_max: number }
> = {
  displacement: { y_min: -120, y_max: 40 },
  velocity: { y_min: -220, y_max: -40 },
  velocity_nm: { y_min: -40, y_max: 140 },
  acceleration: { y_min: -210, y_max: -30 },
  pressure: { y_min: -100, y_max: 40 },
};

export const YAXIS_OPTIONS: {
  value: YAxisType;
  kind: string;
  label: string;
}[] = [
  {
    value: "displacement",
    kind: "변위 (Displacement)",
    label: "PSD [dB rel. m²/Hz]",
  },
  {
    value: "velocity",
    kind: "속도 (Velocity)",
    label: "PSD [dB rel. (m/s)²/Hz]",
  },
  {
    value: "velocity_nm",
    kind: "속도 nm/s (Velocity nm/s)",
    label: "PSD [dB rel. (nm/s)²/Hz]",
  },
  {
    value: "acceleration",
    kind: "가속도 (Acceleration)",
    label: "PSD [dB rel. (m/s²)²/Hz]",
  },
  {
    value: "pressure",
    kind: "음압 (Acoustic Pressure)",
    label: "PSD [dB rel. Pa²/Hz]",
  },
];

export function yaxisSelectLabel(o: (typeof YAXIS_OPTIONS)[number]) {
  return `${o.kind} — ${o.label}`;
}

export function yLimitsForType(t: YAxisType) {
  return YAXIS_DEFAULT_LIMITS[t];
}

/**
 * Infer the Y-axis data type from a SEED channel code (2nd char = instrument):
 *   D           -> pressure (infrasound/pressure, e.g. BDF/HDF)
 *   G/N/A/H/L   -> acceleration (e.g. HGZ, HNZ, HHZ, ELZ, …)
 * Returns null for unknown instrument codes (no auto-selection).
 */
export function yaxisTypeForChannel(
  channel: string | null | undefined
): YAxisType | null {
  const ch = (channel || "").toUpperCase();
  if (ch.length < 2) return null;
  switch (ch[1]) {
    case "D":
      return "pressure";
    case "G":
    case "N":
    case "A":
    case "H":
    case "L":
      return "acceleration";
    default:
      return null;
  }
}

/**
 * Infer a single Y-axis type from multiple channels. Returns the common type
 * only when all recognized channels agree; null if they conflict or none map.
 */
export function yaxisTypeForChannels(
  channels: (string | null | undefined)[]
): YAxisType | null {
  let found: YAxisType | null = null;
  for (const c of channels) {
    const t = yaxisTypeForChannel(c);
    if (t == null) continue;
    if (found == null) found = t;
    else if (found !== t) return null;
  }
  return found;
}
