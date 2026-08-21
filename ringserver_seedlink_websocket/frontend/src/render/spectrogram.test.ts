import { describe, expect, it } from "vitest";
import {
  computeSpectrogram,
  finitePercentile,
  jetRgb,
  spectrogramFreqRange,
  spectrogramFreqTicks,
} from "./spectrogram";

function sine(fs: number, hz: number, seconds: number, amp = 1) {
  const n = Math.floor(fs * seconds);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = amp * Math.sin((2 * Math.PI * hz * i) / fs);
  return out;
}

describe("jetRgb", () => {
  it("starts near dark blue and ends near dark red", () => {
    const [r0, g0, b0] = jetRgb(0);
    const [r1, g1, b1] = jetRgb(1);
    expect(b0).toBeGreaterThan(r0);
    expect(b0).toBeGreaterThan(g0);
    expect(r1).toBeGreaterThan(b1);
    expect(r1).toBeGreaterThan(g1);
  });

  it("is greenest near the midpoint", () => {
    const [, gMid] = jetRgb(0.5);
    const [, gLow] = jetRgb(0.15);
    const [, gHigh] = jetRgb(0.85);
    expect(gMid).toBeGreaterThan(gLow);
    expect(gMid).toBeGreaterThan(gHigh);
  });
});

describe("spectrogramFreqRange", () => {
  it("locks Y-axis to 0–Nyquist from the sample rate", () => {
    expect(spectrogramFreqRange(10)).toEqual({ fMin: 0, fMax: 5 });
    expect(spectrogramFreqRange(20)).toEqual({ fMin: 0, fMax: 10 });
    expect(spectrogramFreqRange(100)).toEqual({ fMin: 0, fMax: 50 });
    expect(spectrogramFreqRange(200)).toEqual({ fMin: 0, fMax: 100 });
  });

  it("snaps near-integer Nyquist values", () => {
    expect(spectrogramFreqRange(99.98).fMax).toBe(50);
  });

  it("uses Nyquist-based ticks", () => {
    expect(spectrogramFreqTicks(5, 80)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(spectrogramFreqTicks(50, 80)).toEqual([0, 10, 20, 30, 40, 50]);
    expect(spectrogramFreqTicks(50, 50)).toEqual([0, 25, 50]);
    expect(spectrogramFreqTicks(5, 30)).toEqual([0, 5]);
  });
});

describe("computeSpectrogram", () => {
  it("returns empty for too few samples", () => {
    const spec = computeSpectrogram(new Float32Array(8), 100);
    expect(spec.frames).toBe(0);
    expect(spec.db.length).toBe(0);
  });

  it("concentrates energy near the sine frequency", () => {
    const fs = 100;
    const hz = 10;
    const spec = computeSpectrogram(sine(fs, hz, 8), fs);
    expect(spec.frames).toBeGreaterThan(1);
    expect(spec.bins).toBeGreaterThan(8);

    const mean = new Float32Array(spec.bins);
    for (let f = 0; f < spec.frames; f++) {
      for (let b = 0; b < spec.bins; b++) {
        mean[b]! += spec.db[f * spec.bins + b]!;
      }
    }
    let peak = 1;
    for (let b = 1; b < spec.bins; b++) {
      if (mean[b]! > mean[peak]!) peak = b;
    }
    expect(Math.abs(spec.freqs[peak]! - hz)).toBeLessThan(1);
    const nyq = spectrogramFreqRange(fs).fMax;
    expect(spec.freqs[spec.bins - 1]!).toBeLessThanOrEqual(nyq);
  });

  it("keeps a moderate STFT size for multi-stream performance", () => {
    const spec = computeSpectrogram(sine(100, 10, 30), 100, { timeCols: 400 });
    expect(spec.nfft).toBe(256);
    expect(spec.nfft).toBeLessThanOrEqual(512);
    expect(spec.frames).toBeGreaterThan(20);
    expect(spec.frames).toBeLessThanOrEqual(320);
  });
});

describe("finitePercentile", () => {
  it("returns interpolated percentiles of finite values", () => {
    const v = new Float32Array([10, 20, 30, 40, Number.NaN]);
    expect(finitePercentile(v, 0)).toBe(10);
    expect(finitePercentile(v, 1)).toBe(40);
    expect(finitePercentile(v, 0.5)).toBe(25);
  });
});
