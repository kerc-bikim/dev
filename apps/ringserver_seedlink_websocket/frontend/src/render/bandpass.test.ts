import { describe, expect, it } from "vitest";
import { applyBandPass, applyBandPassCached, applyBandPassDetailed } from "./bandpass";

function sine(fs: number, hz: number, seconds: number, amp = 1) {
  const n = Math.floor(fs * seconds);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = amp * Math.sin((2 * Math.PI * hz * i) / fs);
  return out;
}

function rms(x: Float32Array) {
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i]! * x[i]!;
  return Math.sqrt(s / x.length);
}

describe("applyBandPass", () => {
  it("passes energy inside the band and attenuates outside", () => {
    const fs = 100;
    const inBand = sine(fs, 2, 8);
    const outBand = sine(fs, 20, 8);
    const filteredIn = applyBandPass(inBand, fs, 1, 5);
    const filteredOut = applyBandPass(outBand, fs, 1, 5);
    expect(rms(filteredIn)).toBeGreaterThan(0.3);
    expect(rms(filteredOut)).toBeLessThan(0.15);
  });

  it("clamps fmax to Nyquist instead of skipping", () => {
    const fs = 20;
    const x = sine(fs, 2, 6);
    const r = applyBandPassDetailed(x, fs, 0.5, 40);
    expect(r.applied).toBe(true);
    expect(r.clamped).toBe(true);
    expect(r.fmaxHz).toBeLessThan(fs / 2);
  });

  it("returns a copy when the band is entirely above Nyquist", () => {
    const fs = 20;
    const x = sine(fs, 2, 4);
    const r = applyBandPassDetailed(x, fs, 30, 40);
    expect(r.applied).toBe(false);
    expect(r.samples.length).toBe(x.length);
  });

  it("reuses cache for identical window keys", () => {
    const x = sine(100, 2, 4);
    const a = applyBandPassCached("ch", x, 100, 0, 4000, 1, 5);
    const b = applyBandPassCached("ch", x, 100, 0, 4000, 1, 5);
    expect(a).toBe(b);
  });

  it("invalidates cache when middle samples change in the same window", () => {
    const x = sine(100, 2, 4);
    const a = applyBandPassCached("changing-ch", x, 100, 0, 4000, 1, 5);
    x[Math.floor(x.length / 2)] += 10;
    const b = applyBandPassCached("changing-ch", x, 100, 0, 4000, 1, 5);
    expect(b).not.toBe(a);
  });
});
