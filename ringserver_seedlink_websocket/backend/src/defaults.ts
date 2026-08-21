import {
  BUILTIN_BANDPASS_PRESETS,
  mergeBandPassPresets,
  type BandPassPreset,
} from "./bandPassPresets.js";
import {
  DEFAULT_SPECTROGRAM,
  type SpectrogramSettings,
} from "./spectrogramSettings.js";

export type WaveformColors = {
  palette: string[];
  channelColorMap: Record<string, string>;
  gapColor: string;
  selectionColor: string;
};

export type XAxisRightAnchor = "now" | "lastData";
export type YScaleMode = "auto" | "uniform";

export type AppSettings = {
  ringserverUrl: string;
  fdsnwsUrl: string;
  protocol: "datalink";
  durationSec: number;
  refreshIntervalMs: number;
  maxPanels: number;
  amplitudeMode: "raw" | "physical";
  yScaleMode: YScaleMode;
  xAxisRightAnchor: XAxisRightAnchor;
  waveformColors: WaveformColors;
  bandPassEnabled: boolean;
  bandPassPresetId: string | null;
  bandPassPresets: BandPassPreset[];
  spectrogram: SpectrogramSettings;
};

export const DEFAULT_SETTINGS: AppSettings = {
  ringserverUrl: process.env.RINGSERVER_URL || "http://localhost:18000",
  fdsnwsUrl: process.env.FDSNWS_URL || "http://172.31.100.100/fdsnws",
  protocol: "datalink",
  durationSec: 300,
  refreshIntervalMs: 500,
  maxPanels: 16,
  amplitudeMode: "raw",
  yScaleMode: "auto",
  xAxisRightAnchor: "lastData",
  waveformColors: {
    palette: [
      "#3dd6c6",
      "#e9c46a",
      "#7aa2ff",
      "#ff8fab",
      "#9bdeac",
      "#f4a261",
      "#c77dff",
      "#90e0ef",
    ],
    channelColorMap: {},
    gapColor: "#ff4d4f",
    selectionColor: "#ffd166",
  },
  bandPassEnabled: false,
  bandPassPresetId: null,
  bandPassPresets: [...BUILTIN_BANDPASS_PRESETS],
  spectrogram: { ...DEFAULT_SPECTROGRAM },
};

export { BUILTIN_BANDPASS_PRESETS, mergeBandPassPresets };
export type { BandPassPreset };

export const DURATION_MAX = 86400;
export const MAX_PANELS_HARD = 50;
