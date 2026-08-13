/**
 * Butterworth band-pass (order 4 = HP2 + LP2) + zero-phase filtfilt
 * with odd extension + Gustafsson-style initial conditions.
 */

import { clampBandPassToNyquist } from "../../../shared/bandPassPresets";

type Biquad = {
  b0: number;
  b1: number;
  b2: number;
  a1: number;
  a2: number;
};

const MIN_SAMPLES = 16;

export type BandPassResult = {
  samples: Float32Array;
  applied: boolean;
  clamped: boolean;
  fminHz: number;
  fmaxHz: number;
};

function butterworthQs(order: number): number[] {
  const qs: number[] = [];
  const sections = order / 2;
  for (let k = 0; k < sections; k++) {
    qs.push(1 / (2 * Math.sin((Math.PI * (2 * k + 1)) / (2 * order))));
  }
  return qs;
}

function lowpassBiquad(fc: number, fs: number, q: number): Biquad {
  const w0 = (2 * Math.PI * fc) / fs;
  const cosw = Math.cos(w0);
  const sinw = Math.sin(w0);
  const alpha = sinw / (2 * q);
  const b0 = (1 - cosw) / 2;
  const b1 = 1 - cosw;
  const b2 = (1 - cosw) / 2;
  const a0 = 1 + alpha;
  const a1 = -2 * cosw;
  const a2 = 1 - alpha;
  return {
    b0: b0 / a0,
    b1: b1 / a0,
    b2: b2 / a0,
    a1: a1 / a0,
    a2: a2 / a0,
  };
}

function highpassBiquad(fc: number, fs: number, q: number): Biquad {
  const w0 = (2 * Math.PI * fc) / fs;
  const cosw = Math.cos(w0);
  const sinw = Math.sin(w0);
  const alpha = sinw / (2 * q);
  const b0 = (1 + cosw) / 2;
  const b1 = -(1 + cosw);
  const b2 = (1 + cosw) / 2;
  const a0 = 1 + alpha;
  const a1 = -2 * cosw;
  const a2 = 1 - alpha;
  return {
    b0: b0 / a0,
    b1: b1 / a0,
    b2: b2 / a0,
    a1: a1 / a0,
    a2: a2 / a0,
  };
}

function designBandPassSos(fmin: number, fmax: number, fs: number): Biquad[] {
  const qs = butterworthQs(4);
  const sos: Biquad[] = [];
  for (const q of qs) sos.push(highpassBiquad(fmin, fs, q));
  for (const q of qs) sos.push(lowpassBiquad(fmax, fs, q));
  return sos;
}

/**
 * Steady-state zi for constant input x0 (Direct Form II Transposed).
 * y0 = (b0+b1+b2)/(1+a1+a2)*x0
 * z1 = (b2 - a2*y0/x0)*x0  if x0!=0 else 0
 * z0 = (b1 - a1*y0/x0)*x0 + z1
 */
function lfilterZi(bq: Biquad, x0: number): [number, number] {
  const { b0, b1, b2, a1, a2 } = bq;
  if (!Number.isFinite(x0) || x0 === 0) return [0, 0];
  const den = 1 + a1 + a2;
  if (Math.abs(den) < 1e-18) return [0, 0];
  const y0 = ((b0 + b1 + b2) / den) * x0;
  const zi1 = b2 * x0 - a2 * y0;
  const zi0 = b1 * x0 - a1 * y0 + zi1;
  return [zi0, zi1];
}

function sosfiltOne(
  bq: Biquad,
  x: Float32Array,
  zi0 = 0,
  zi1 = 0,
): { y: Float32Array; zf0: number; zf1: number } {
  const y = new Float32Array(x.length);
  let z0 = zi0;
  let z1 = zi1;
  const { b0, b1, b2, a1, a2 } = bq;
  for (let i = 0; i < x.length; i++) {
    const xi = x[i]!;
    const yi = b0 * xi + z0;
    z0 = b1 * xi - a1 * yi + z1;
    z1 = b2 * xi - a2 * yi;
    y[i] = yi;
  }
  return { y, zf0: z0, zf1: z1 };
}

function reverseCopy(x: Float32Array): Float32Array {
  const y = new Float32Array(x.length);
  for (let i = 0, j = x.length - 1; i < x.length; i++, j--) y[i] = x[j]!;
  return y;
}

/**
 * scipy.signal.filtfilt(method='gust') lite:
 * odd extension + steady-state zi at both ends, forward then backward.
 */
function filtfilt(sos: Biquad[], x: Float32Array): Float32Array {
  const n = x.length;
  if (n < MIN_SAMPLES || !sos.length) return new Float32Array(x);

  const pad = Math.min(n - 1, Math.max(3 * sos.length * 3, 48));
  const ext = new Float32Array(n + 2 * pad);
  for (let i = 0; i < pad; i++) {
    ext[i] = 2 * x[0]! - x[pad - i]!;
  }
  ext.set(x, pad);
  for (let i = 0; i < pad; i++) {
    ext[pad + n + i] = 2 * x[n - 1]! - x[n - 2 - i]!;
  }

  let cur: Float32Array = ext;
  for (const bq of sos) {
    const [zi0, zi1] = lfilterZi(bq, cur[0]!);
    cur = sosfiltOne(bq, cur, zi0, zi1).y;
  }

  cur = reverseCopy(cur);
  for (const bq of sos) {
    const [zi0, zi1] = lfilterZi(bq, cur[0]!);
    cur = sosfiltOne(bq, cur, zi0, zi1).y;
  }
  cur = reverseCopy(cur);

  return new Float32Array(cur.subarray(pad, pad + n));
}

/**
 * Apply zero-phase Butterworth band-pass.
 * Cutoffs are clamped inside Nyquist; invalid params copy input.
 */
export function applyBandPass(
  samples: Float32Array,
  sampleRate: number,
  fminHz: number,
  fmaxHz: number,
): Float32Array {
  return applyBandPassDetailed(samples, sampleRate, fminHz, fmaxHz).samples;
}

export function applyBandPassDetailed(
  samples: Float32Array,
  sampleRate: number,
  fminHz: number,
  fmaxHz: number,
): BandPassResult {
  const copy = () =>
    ({
      samples: new Float32Array(samples),
      applied: false,
      clamped: false,
      fminHz,
      fmaxHz,
    }) satisfies BandPassResult;

  if (!samples.length || !(sampleRate > 0)) return copy();
  if (samples.length < MIN_SAMPLES) return copy();

  const nyq = clampBandPassToNyquist(fminHz, fmaxHz, sampleRate);
  if (!nyq) return { ...copy(), clamped: true };

  const sos = designBandPassSos(nyq.fminHz, nyq.fmaxHz, sampleRate);
  if (!sos.length) return { ...copy(), clamped: nyq.clamped };

  try {
    const out = filtfilt(sos, samples);
    return {
      samples: new Float32Array(out),
      applied: true,
      clamped: nyq.clamped,
      fminHz: nyq.fminHz,
      fmaxHz: nyq.fmaxHz,
    };
  } catch {
    return { ...copy(), clamped: nyq.clamped };
  }
}

type CacheEntry = {
  key: string;
  source: Float32Array;
  samples: Float32Array;
};

const filterCache = new Map<string, CacheEntry>();
const MAX_CACHE = 64;

function cacheKey(
  channelKey: string,
  windowStartMs: number,
  windowEndMs: number,
  sampleRate: number,
  n: number,
  fmin: number,
  fmax: number,
): string {
  return `${channelKey}|${windowStartMs}|${windowEndMs}|${sampleRate}|${n}|${fmin}|${fmax}`;
}

function samplesEqual(a: Float32Array, b: Float32Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (!Object.is(a[i], b[i])) return false;
  }
  return true;
}

/** 채널·윈도우·컷오프와 전체 입력 샘플이 같으면 재사용 */
export function applyBandPassCached(
  channelKey: string,
  samples: Float32Array,
  sampleRate: number,
  windowStartMs: number,
  windowEndMs: number,
  fminHz: number,
  fmaxHz: number,
): Float32Array {
  if (!samples.length) return new Float32Array(samples);
  const key = cacheKey(
    channelKey,
    windowStartMs,
    windowEndMs,
    sampleRate,
    samples.length,
    fminHz,
    fmaxHz,
  );
  const hit = filterCache.get(channelKey);
  if (hit && hit.key === key && samplesEqual(hit.source, samples)) return hit.samples;

  const out = applyBandPass(samples, sampleRate, fminHz, fmaxHz);
  if (filterCache.size >= MAX_CACHE && !filterCache.has(channelKey)) {
    const oldest = filterCache.keys().next().value;
    if (oldest) filterCache.delete(oldest);
  }
  filterCache.set(channelKey, {
    key,
    source: new Float32Array(samples),
    samples: out,
  });
  return out;
}

export function clearBandPassCache(channelKey?: string) {
  if (channelKey) filterCache.delete(channelKey);
  else filterCache.clear();
}
