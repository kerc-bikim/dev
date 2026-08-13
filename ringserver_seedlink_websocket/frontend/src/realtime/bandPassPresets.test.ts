import { describe, expect, it } from "vitest";
import {
  BUILTIN_BANDPASS_PRESETS,
  clampBandPassToNyquist,
  mergeBandPassPresets,
  resolveBandPass,
  sanitizeBandPassPresets,
} from "./bandPassPresets";

describe("mergeBandPassPresets", () => {
  it("keeps all builtin presets even if storage is empty", () => {
    const merged = mergeBandPassPresets([]);
    expect(merged.filter((p) => p.builtin).map((p) => p.id)).toEqual(
      BUILTIN_BANDPASS_PRESETS.map((p) => p.id),
    );
  });

  it("appends valid custom presets and ignores invalid ones", () => {
    const merged = mergeBandPassPresets([
      { id: "c1", name: "Mine", fminHz: 0.2, fmaxHz: 4, group: "custom" },
      { id: "bad", name: "Bad", fminHz: 5, fmaxHz: 1, group: "custom" },
    ]);
    expect(merged.some((p) => p.id === "c1")).toBe(true);
    expect(merged.some((p) => p.id === "bad")).toBe(false);
  });

  it("does not let custom overwrite builtin ids", () => {
    const merged = mergeBandPassPresets([
      {
        id: "seis-1-5",
        name: "Hijack",
        fminHz: 2,
        fmaxHz: 3,
        group: "custom",
      },
    ]);
    const seis = merged.find((p) => p.id === "seis-1-5")!;
    expect(seis.fminHz).toBe(1);
    expect(seis.builtin).toBe(true);
  });
});

describe("resolveBandPass", () => {
  it("returns null when off", () => {
    expect(resolveBandPass(false, "seis-1-5", BUILTIN_BANDPASS_PRESETS)).toBeNull();
  });

  it("resolves builtin preset cutoffs", () => {
    expect(resolveBandPass(true, "seis-1-5", BUILTIN_BANDPASS_PRESETS)).toEqual({
      fminHz: 1,
      fmaxHz: 5,
    });
  });
});

describe("clampBandPassToNyquist", () => {
  it("clamps fmax below Nyquist", () => {
    const r = clampBandPassToNyquist(1, 40, 20);
    expect(r).not.toBeNull();
    expect(r!.clamped).toBe(true);
    expect(r!.fmaxHz).toBeLessThan(10);
    expect(r!.fminHz).toBe(1);
  });

  it("returns null when the whole band is above Nyquist", () => {
    expect(clampBandPassToNyquist(30, 40, 20)).toBeNull();
  });
});

describe("sanitizeBandPassPresets", () => {
  it("drops non-arrays", () => {
    expect(sanitizeBandPassPresets("nope")).toBeUndefined();
  });

  it("merges sanitized custom entries", () => {
    const out = sanitizeBandPassPresets([
      { id: "c2", name: "OK", fminHz: 0.5, fmaxHz: 2, group: "custom" },
    ]);
    expect(out?.some((p) => p.id === "c2")).toBe(true);
  });
});
