import FFT from "fft.js";
import {
  DEFAULT_SPECTROGRAM,
  sanitizeSpectrogramSettings,
  type SpectrogramSettings,
} from "./spectrogramSettings";

export type SpectrogramResult = {
  /** row-major dB: frames * bins */
  db: Float32Array;
  frames: number;
  bins: number;
  nfft: number;
  hop: number;
  sampleRate: number;
  /** 각 프레임 중심 시각 (첫 샘플 기준, 초) */
  timesSec: Float32Array;
  freqs: Float32Array;
};

function floorPow2(n: number): number {
  if (n < 2) return 0;
  let p = 1;
  while (p <= n >> 1) p <<= 1;
  return p;
}

function clamp01(v: number): number {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}

/** MATLAB-style jet colormap. t ∈ [0, 1] → RGB 0..255 */
export function jetRgb(t: number): [number, number, number] {
  const x = clamp01(t);
  const r = clamp01(1.5 - Math.abs(4 * x - 3));
  const g = clamp01(1.5 - Math.abs(4 * x - 2));
  const b = clamp01(1.5 - Math.abs(4 * x - 1));
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

export const SPECTROGRAM_FMIN_HZ = 0;

function niceNyquist(sampleRate: number): number {
  const nyq = sampleRate / 2;
  if (!(nyq > 0) || !Number.isFinite(nyq)) return 0;
  if (nyq >= 1 && Math.abs(nyq - Math.round(nyq)) < 0.05) return Math.round(nyq);
  return nyq;
}

/**
 * 스펙트로그램 Y축: 0 Hz ~ Nyquist(fs/2)로 고정하고 패널 높이를 가득 채운다.
 * 10 sps → 0–5 Hz, 100 sps → 0–50 Hz.
 */
export function spectrogramFreqRange(sampleRate: number): { fMin: number; fMax: number } {
  return { fMin: SPECTROGRAM_FMIN_HZ, fMax: niceNyquist(sampleRate) };
}

export function spectrogramFreqTicks(fMax: number, plotH: number): number[] {
  if (!(fMax > 0)) return [0];
  const maxTicks = plotH > 72 ? 6 : plotH > 40 ? 3 : 2;
  const target = fMax / Math.max(1, maxTicks - 1);
  const nice = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200];
  let step = nice[nice.length - 1]!;
  for (const s of nice) {
    if (s >= target - 1e-12) {
      step = s;
      break;
    }
  }
  const ticks: number[] = [];
  for (let v = 0; v < fMax - step * 0.2; v += step) ticks.push(Number(v.toPrecision(8)));
  ticks.push(fMax);
  return ticks;
}

function nextPow2(n: number): number {
  if (n <= 1) return 1;
  let p = 1;
  while (p < n) p <<= 1;
  return p;
}

function pickNfft(
  nSamples: number,
  sampleRate: number,
  windowSec: number,
  nfftMax: number,
): number {
  if (nSamples < 32 || !(sampleRate > 0)) return 0;
  const targetLen = Math.round(sampleRate * windowSec);
  let nfft = nextPow2(Math.max(64, targetLen));
  nfft = Math.min(nfftMax, nfft);
  if (nfft > nSamples) nfft = floorPow2(nSamples);
  return nfft >= 32 ? nfft : 0;
}

/**
 * 표시 구간 샘플의 STFT (Hann, 양수 주파수, 파워 dB).
 * 시간 축은 첫 샘플 기준이며, 호출 측에서 window 시각에 맞춘다.
 */
export function computeSpectrogram(
  samples: Float32Array,
  sampleRate: number,
  opts?: Partial<SpectrogramSettings> & { timeCols?: number },
): SpectrogramResult {
  const empty: SpectrogramResult = {
    db: new Float32Array(0),
    frames: 0,
    bins: 0,
    nfft: 0,
    hop: 0,
    sampleRate,
    timesSec: new Float32Array(0),
    freqs: new Float32Array(0),
  };
  if (samples.length < 32 || sampleRate <= 0) return empty;

  const cfg = sanitizeSpectrogramSettings({ ...DEFAULT_SPECTROGRAM, ...opts });
  const nfft = pickNfft(samples.length, sampleRate, cfg.windowSec, cfg.nfftMax);
  if (nfft < 32) return empty;

  const maxFrames = Math.min(
    cfg.maxFrames,
    Math.max(32, Math.floor(opts?.timeCols ?? cfg.maxFrames)),
  );
  const minHop = Math.max(1, Math.floor(nfft / cfg.hopDivisor));
  const hop = Math.max(
    minHop,
    Math.ceil((samples.length - nfft) / Math.max(1, maxFrames - 1)),
  );
  const frames = Math.floor((samples.length - nfft) / hop) + 1;
  if (frames < 1) return empty;

  const bins = nfft / 2;
  const fft = new FFT(nfft);
  const input = fft.createComplexArray();
  const output = fft.createComplexArray();
  const window = new Float32Array(nfft);
  for (let i = 0; i < nfft; i++) {
    window[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / Math.max(1, nfft - 1)));
  }

  const db = new Float32Array(frames * bins);
  const timesSec = new Float32Array(frames);
  const freqs = new Float32Array(bins);
  for (let b = 0; b < bins; b++) freqs[b] = (b * sampleRate) / nfft;

  for (let f = 0; f < frames; f++) {
    const off = f * hop;
    timesSec[f] = (off + nfft / 2) / sampleRate;
    for (let i = 0; i < nfft; i++) {
      input[i * 2] = samples[off + i]! * window[i]!;
      input[i * 2 + 1] = 0;
    }
    fft.transform(output, input);
    const row = f * bins;
    for (let b = 0; b < bins; b++) {
      const re = output[b * 2]!;
      const im = output[b * 2 + 1]!;
      const mag = Math.sqrt(re * re + im * im) / nfft;
      db[row + b] = 20 * Math.log10(mag + 1e-12);
    }
  }

  return { db, frames, bins, nfft, hop, sampleRate, timesSec, freqs };
}

/** 유한값의 백분위 (p ∈ [0, 1]). */
export function finitePercentile(values: Float32Array, p: number): number {
  const stride = values.length > 16384 ? 4 : 1;
  const xs: number[] = [];
  for (let i = 0; i < values.length; i += stride) {
    const v = values[i]!;
    if (Number.isFinite(v)) xs.push(v);
  }
  if (!xs.length) return 0;
  xs.sort((a, b) => a - b);
  const t = Math.min(1, Math.max(0, p)) * (xs.length - 1);
  const lo = Math.floor(t);
  const hi = Math.ceil(t);
  if (lo === hi) return xs[lo]!;
  return xs[lo]! * (hi - t) + xs[hi]! * (t - lo);
}
