/** Canonical copy: keep in sync with shared/spectrogramSettings.ts (backend tsc rootDir=src). */

export type SpectrogramHopDivisor = 2 | 4 | 8;

export type SpectrogramSettings = {
  windowSec: number;
  nfftMax: number;
  maxFrames: number;
  hopDivisor: SpectrogramHopDivisor;
};

export const DEFAULT_SPECTROGRAM: SpectrogramSettings = {
  windowSec: 2,
  nfftMax: 512,
  maxFrames: 320,
  hopDivisor: 4,
};

function clampNum(n: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

function nearestPow2(n: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(n) || n <= 0) return fallback;
  let p = 1;
  while (p < n) p <<= 1;
  const lo = p >> 1;
  const pick = n - lo < p - n && lo >= min ? lo : p;
  return Math.min(max, Math.max(min, pick));
}

export function sanitizeSpectrogramSettings(raw: unknown): SpectrogramSettings {
  const d = DEFAULT_SPECTROGRAM;
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const hopRaw = Number(o.hopDivisor);
  const hopDivisor: SpectrogramHopDivisor =
    hopRaw === 2 || hopRaw === 4 || hopRaw === 8 ? hopRaw : d.hopDivisor;
  return {
    windowSec: clampNum(Number(o.windowSec), 1, 8, d.windowSec),
    nfftMax: nearestPow2(Number(o.nfftMax), 128, 1024, d.nfftMax),
    maxFrames: Math.round(clampNum(Number(o.maxFrames), 64, 1024, d.maxFrames)),
    hopDivisor,
  };
}
