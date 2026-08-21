import { describe, expect, it } from "vitest";
import {
  DEFAULT_SPECTROGRAM,
  sanitizeSpectrogramSettings,
} from "./spectrogramSettings";

describe("sanitizeSpectrogramSettings", () => {
  it("returns defaults for missing or invalid input", () => {
    expect(sanitizeSpectrogramSettings(undefined)).toEqual(DEFAULT_SPECTROGRAM);
    expect(sanitizeSpectrogramSettings(null)).toEqual(DEFAULT_SPECTROGRAM);
    expect(sanitizeSpectrogramSettings({ windowSec: "nope" })).toEqual(DEFAULT_SPECTROGRAM);
  });

  it("clamps values into the allowed range", () => {
    const out = sanitizeSpectrogramSettings({
      windowSec: 99,
      nfftMax: 300,
      maxFrames: 8,
      hopDivisor: 3,
    });
    expect(out.windowSec).toBe(8);
    expect(out.nfftMax).toBe(256);
    expect(out.maxFrames).toBe(64);
    expect(out.hopDivisor).toBe(4);
  });

  it("keeps the current performance defaults", () => {
    expect(DEFAULT_SPECTROGRAM).toEqual({
      windowSec: 2,
      nfftMax: 512,
      maxFrames: 320,
      hopDivisor: 4,
    });
  });
});
