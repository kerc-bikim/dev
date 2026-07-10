import { AxisRangePanel, AxisRangeValue } from "./AxisRangePanel";
import type { YAxisType } from "../api/client";
import { yLimitsForType, YAXIS_OPTIONS, yaxisSelectLabel } from "../utils/yaxisDefaults";

export type { YAxisType };

export interface PlotOptionsValue extends AxisRangeValue {
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
}

export const DEFAULT_PLOT_OPTIONS: PlotOptionsValue = {
  percentile_low: 10,
  percentile_high: 90,
  show_overlay: true,
  clip_to_percentile: false,
  xaxis: "period",
  yaxis_type: "acceleration",
  show_noise_models: true,
  show_mean: false,
  show_mode: false,
  cmap: "viridis",
  x_min: null,
  x_max: null,
  y_min: -210,
  y_max: -30,
};

const CMAP_OPTIONS = [
  "viridis", "magma", "plasma", "inferno", "cividis", "turbo", "hot", "jet",
];

interface Props {
  value: PlotOptionsValue;
  onChange: (v: PlotOptionsValue) => void;
  showPercentiles?: boolean;
  showAxisRange?: boolean;
}

export function PlotOptionsPanel({
  value,
  onChange,
  showPercentiles = true,
  showAxisRange = true,
}: Props) {
  const set = <K extends keyof PlotOptionsValue>(k: K, v: PlotOptionsValue[K]) =>
    onChange({ ...value, [k]: v });

  return (
    <>
      {showPercentiles && (
        <div className="section">
          <h3>Percentiles</h3>
          <div className="range-row">
            <span>Low</span>
            <input
              type="range"
              min={0}
              max={50}
              step={1}
              value={value.percentile_low}
              onChange={(e) => set("percentile_low", Number(e.target.value))}
            />
            <span>{value.percentile_low}</span>
          </div>
          <div className="range-row">
            <span>High</span>
            <input
              type="range"
              min={50}
              max={100}
              step={1}
              value={value.percentile_high}
              onChange={(e) => set("percentile_high", Number(e.target.value))}
            />
            <span>{value.percentile_high}</span>
          </div>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={value.show_overlay}
              onChange={(e) => set("show_overlay", e.target.checked)}
            />
            Overlay percentile curves
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={value.clip_to_percentile}
              onChange={(e) => set("clip_to_percentile", e.target.checked)}
            />
            Clip histogram to percentile range
          </label>
        </div>
      )}

      <div className="section">
        <h3>Plot options</h3>
        <div className="row-2">
          <div className="field">
            <label>X axis</label>
            <select
              value={value.xaxis}
              onChange={(e) =>
                set("xaxis", e.target.value as "period" | "frequency")
              }
            >
              <option value="period">Period [s]</option>
              <option value="frequency">Frequency [Hz]</option>
            </select>
          </div>
          <div className="field">
            <label>Y axis (데이터 종류)</label>
            <select
              value={value.yaxis_type}
              onChange={(e) => {
                const t = e.target.value as YAxisType;
                const lim = yLimitsForType(t);
                onChange({
                  ...value,
                  yaxis_type: t,
                  y_min: lim.y_min,
                  y_max: lim.y_max,
                });
              }}
            >
              {YAXIS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {yaxisSelectLabel(o)}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label>Colormap</label>
          <select
            value={value.cmap}
            onChange={(e) => set("cmap", e.target.value)}
          >
            {CMAP_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={value.show_noise_models}
            onChange={(e) => set("show_noise_models", e.target.checked)}
          />
          Show Peterson NLNM / NHNM
        </label>
        {showPercentiles && (
          <>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={value.show_mode}
                onChange={(e) => set("show_mode", e.target.checked)}
              />
              Show mode curve
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={value.show_mean}
                onChange={(e) => set("show_mean", e.target.checked)}
              />
              Show mean curve
            </label>
          </>
        )}
      </div>

      {showAxisRange && (
        <AxisRangePanel
          value={value}
          onChange={(axis) => onChange({ ...value, ...axis })}
          xaxis={value.xaxis}
        />
      )}
    </>
  );
}
