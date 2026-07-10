export interface NetworkInfo {
  code: string;
  description?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  total_stations?: number | null;
}

export interface StationInfo {
  network: string;
  code: string;
  name?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  elevation?: number | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface ChannelInfo {
  network: string;
  station: string;
  location: string;
  channel: string;
  sample_rate?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  azimuth?: number | null;
  dip?: number | null;
}

export interface ChannelTarget {
  network: string;
  station: string;
  location: string;
  channel: string;
  label?: string;
  color?: string;
}

export interface PlotOptions {
  percentile_low: number;
  percentile_high: number;
  show_overlay: boolean;
  clip_to_percentile: boolean;
  xaxis: "period" | "frequency";
  yaxis_type: YAxisType;
  show_noise_models: boolean;
  show_mean: boolean;
  show_mode: boolean;
  cmap: string;
  x_min?: number | null;
  x_max?: number | null;
  y_min?: number | null;
  y_max?: number | null;
}

export interface PPSDRequestBody {
  network: string;
  station: string;
  location: string;
  channel: string;
  starttime: string;
  endtime: string;
  percentile_low: number;
  percentile_high: number;
  show_overlay: boolean;
  clip_to_percentile: boolean;
  xaxis: "period" | "frequency";
  yaxis_type: YAxisType;
  show_noise_models: boolean;
  show_mean: boolean;
  show_mode: boolean;
  cmap: string;
  x_min?: number | null;
  x_max?: number | null;
  y_min?: number | null;
  y_max?: number | null;
}

export interface PPSDStats {
  segments_used: number;
  starttime: string;
  endtime: string;
  channel_id: string;
  sampling_rate?: number | null;
  from_cache: boolean;
}

export interface CurveData {
  x: number[];
  db: number[];
  label?: string;
  perc?: number;
}

export interface NoiseModels {
  low: CurveData & { label: string };
  high: CurveData & { label: string };
}

export interface AxisLimits {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
}

export interface HeatmapData {
  kind: "heatmap";
  xaxis: "period" | "frequency";
  xlabel: string;
  ylabel: string;
  cmap: string;
  x_edges: number[];
  db_edges: number[];
  histogram: (number | null)[][];
  vmax: number;
  overlays: {
    percentile_low?: CurveData & { perc: number };
    percentile_high?: CurveData & { perc: number };
    mode?: CurveData;
    mean?: CurveData;
  };
  noise_models: NoiseModels | null;
  axis: AxisLimits;
  title: string;
}

export interface CompareSeries {
  label: string;
  color: string;
  curves: (CurveData & { perc: number; label: string })[];
}

export interface CompareData {
  kind: "compare";
  xaxis: "period" | "frequency";
  xlabel: string;
  ylabel: string;
  series: CompareSeries[];
  noise_models: NoiseModels | null;
  axis: AxisLimits;
  title: string;
}

export interface PPSDResponse {
  job_id: string;
  data: HeatmapData;
  stats: PPSDStats;
}

export interface BatchPPSDItem {
  target: ChannelTarget;
  status: "ok" | "error";
  job_id?: string | null;
  data?: HeatmapData | null;
  stats?: PPSDStats | null;
  error?: string | null;
}

export interface BatchPPSDResponse {
  items: BatchPPSDItem[];
  elapsed_seconds: number;
}

export interface BatchPPSDRequestBody {
  targets: ChannelTarget[];
  starttime: string;
  endtime: string;
  options: PlotOptions;
}

export interface CompareRequestBody {
  targets: ChannelTarget[];
  starttime: string;
  endtime: string;
  percentiles: number[];
  xaxis: "period" | "frequency";
  yaxis_type: YAxisType;
  show_noise_models: boolean;
  x_min?: number | null;
  x_max?: number | null;
  y_min?: number | null;
  y_max?: number | null;
}

export interface CompareTimeWindowBody {
  starttime: string;
  endtime: string;
  label?: string;
  color?: string;
}

export interface CompareTimeRequestBody {
  target: ChannelTarget;
  windows: CompareTimeWindowBody[];
  percentiles: number[];
  xaxis: "period" | "frequency";
  yaxis_type: YAxisType;
  show_noise_models: boolean;
  x_min?: number | null;
  x_max?: number | null;
  y_min?: number | null;
  y_max?: number | null;
}

export interface CompareResponse {
  data: CompareData;
  items: BatchPPSDItem[];
  elapsed_seconds: number;
}

export interface PlotDefaults {
  x_min?: number | null;
  x_max?: number | null;
  y_min?: number | null;
  y_max?: number | null;
  yaxis_type?: YAxisType;
}

export type YAxisType =
  | "acceleration"
  | "velocity"
  | "velocity_nm"
  | "displacement"
  | "pressure";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
      else if (body && Array.isArray(body.detail)) {
        detail = body.detail.map((d: any) => d.msg ?? JSON.stringify(d)).join("; ");
      }
    } catch {}
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  networks: () =>
    fetch(`${BASE}/api/networks`).then((r) => jsonOrThrow<NetworkInfo[]>(r)),
  stations: (network: string) =>
    fetch(`${BASE}/api/stations?network=${encodeURIComponent(network)}`).then(
      (r) => jsonOrThrow<StationInfo[]>(r)
    ),
  channels: (network: string, station: string) =>
    fetch(
      `${BASE}/api/channels?network=${encodeURIComponent(
        network
      )}&station=${encodeURIComponent(station)}`
    ).then((r) => jsonOrThrow<ChannelInfo[]>(r)),
  ppsd: (body: PPSDRequestBody) =>
    fetch(`${BASE}/api/ppsd`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => jsonOrThrow<PPSDResponse>(r)),
  ppsdBatch: (body: BatchPPSDRequestBody) =>
    fetch(`${BASE}/api/ppsd/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => jsonOrThrow<BatchPPSDResponse>(r)),
  ppsdCompare: (body: CompareRequestBody) =>
    fetch(`${BASE}/api/ppsd/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => jsonOrThrow<CompareResponse>(r)),
  ppsdCompareTime: (body: CompareTimeRequestBody) =>
    fetch(`${BASE}/api/ppsd/compare-time`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => jsonOrThrow<CompareResponse>(r)),
  plotDefaults: () =>
    fetch(`${BASE}/api/plot-defaults`).then((r) => jsonOrThrow<PlotDefaults>(r)),
};
