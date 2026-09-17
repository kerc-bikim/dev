export type XAxisType = "period" | "frequency";
export type InputMode = "dropdown" | "manual";

/**
 * User-configurable frontend defaults, persisted in localStorage so they keep
 * applying across sessions. These seed the initial plot options of each tab;
 * every value is still overridable per-tab after mount.
 */
export interface AppSettings {
  /** Station/channel input: FDSN dropdowns or typed codes. */
  input_mode: InputMode;
  // Heatmap (Single / Multi) defaults
  percentile_low: number;
  percentile_high: number;
  xaxis: XAxisType;
  show_overlay: boolean;
  clip_to_percentile: boolean;
  show_noise_models: boolean;
  show_mode: boolean;
  show_mean: boolean;
  cmap: string;
  /** Colorbar / heatmap Probability [%] display range. */
  probability_min: number;
  probability_max: number;
  // ObsPy PPSD computation defaults
  ppsd_length: number;
  overlap: number;
  period_step_octaves: number;
  period_smoothing_width_octaves: number;
  // Compare (Compare Station / Compare Time) defaults
  compare_percentiles: string;
}

export const DEFAULT_APP_SETTINGS: AppSettings = {
  input_mode: "dropdown",
  percentile_low: 10,
  percentile_high: 90,
  xaxis: "period",
  show_overlay: true,
  clip_to_percentile: false,
  show_noise_models: true,
  show_mode: false,
  show_mean: false,
  cmap: "viridis",
  probability_min: 0,
  probability_max: 30,
  ppsd_length: 3600,
  overlap: 0.5,
  period_step_octaves: 0.0125,
  period_smoothing_width_octaves: 0.125,
  compare_percentiles: "10, 50, 90",
};

export const CMAP_OPTIONS = [
  "viridis",
  "magma",
  "plasma",
  "inferno",
  "cividis",
  "turbo",
  "hot",
  "jet",
  "pqlx",
];

const STORAGE_KEY = "ppsd_app_settings_v1";

export function loadSettings(): AppSettings {
  if (typeof window === "undefined") return { ...DEFAULT_APP_SETTINGS };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_APP_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<AppSettings>;
    // Merge so newly added settings fall back to defaults.
    const merged = { ...DEFAULT_APP_SETTINGS, ...parsed };
    if (merged.input_mode !== "manual") merged.input_mode = "dropdown";
    return merged;
  } catch {
    return { ...DEFAULT_APP_SETTINGS };
  }
}

export function saveSettings(settings: AppSettings): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

/** Fields of the heatmap PlotOptions that the settings control. */
export interface PlotOptionDefaults {
  percentile_low: number;
  percentile_high: number;
  xaxis: XAxisType;
  show_overlay: boolean;
  clip_to_percentile: boolean;
  show_noise_models: boolean;
  show_mode: boolean;
  show_mean: boolean;
  cmap: string;
}

export function settingsToPlotDefaults(s: AppSettings): PlotOptionDefaults {
  return {
    percentile_low: s.percentile_low,
    percentile_high: s.percentile_high,
    xaxis: s.xaxis,
    show_overlay: s.show_overlay,
    clip_to_percentile: s.clip_to_percentile,
    show_noise_models: s.show_noise_models,
    show_mode: s.show_mode,
    show_mean: s.show_mean,
    cmap: s.cmap,
  };
}

/** ObsPy PPSD compute params taken from settings at submit time. */
export function settingsToComputeDefaults(s: AppSettings) {
  return {
    ppsd_length: s.ppsd_length,
    overlap: s.overlap,
    period_step_octaves: s.period_step_octaves,
    period_smoothing_width_octaves: s.period_smoothing_width_octaves,
  };
}
