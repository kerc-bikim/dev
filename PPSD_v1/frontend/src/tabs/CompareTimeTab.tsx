import { useEffect, useState } from "react";
import {
  TargetListEditor,
  StationRow,
  createDefaultRow,
  expandRowsToTargets,
} from "../components/TargetListEditor";
import {
  TimeWindowListEditor,
  TimeWindowRow,
  createDefaultTimeWindows,
} from "../components/TimeWindowListEditor";
import { AxisRangePanel, EMPTY_AXIS_RANGE, AxisRangeValue } from "../components/AxisRangePanel";
import { api, BatchPPSDItem, YAxisType } from "../api/client";
import { mergePlotDefaults, usePlotDefaults } from "../hooks/usePlotDefaults";
import { yLimitsForType, YAXIS_OPTIONS, yaxisSelectLabel } from "../utils/yaxisDefaults";
import { toIsoUtc } from "../utils/time";

export function CompareTimeTab() {
  const plotDefaults = usePlotDefaults();
  const [rows, setRows] = useState<StationRow[]>([createDefaultRow()]);
  const [timeWindows, setTimeWindows] = useState<TimeWindowRow[]>(
    createDefaultTimeWindows()
  );
  const [percentilesText, setPercentilesText] = useState("10, 50, 90");
  const [xaxis, setXaxis] = useState<"period" | "frequency">("period");
  const [yaxisType, setYaxisType] = useState<YAxisType>("acceleration");
  const [showNoiseModels, setShowNoiseModels] = useState(true);
  const [axisRange, setAxisRange] = useState<AxisRangeValue>({
    ...EMPTY_AXIS_RANGE,
    ...yLimitsForType("acceleration"),
  });
  const [manualMode, setManualMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [items, setItems] = useState<BatchPPSDItem[] | null>(null);
  const [elapsed, setElapsed] = useState<number | undefined>();

  useEffect(() => {
    if (plotDefaults) {
      setAxisRange((a) => mergePlotDefaults(a, plotDefaults));
      if (plotDefaults.yaxis_type) {
        setYaxisType(plotDefaults.yaxis_type);
      }
    }
  }, [plotDefaults]);

  const targets = expandRowsToTargets(rows, false);
  const target = targets[0];
  const percentiles = percentilesText
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n) && n >= 0 && n <= 100);

  const canSubmit =
    !!target &&
    timeWindows.length >= 1 &&
    percentiles.length >= 1 &&
    !loading;

  const submit = async () => {
    if (!target) return;
    setLoading(true);
    setError(null);
    setImageUrl(null);
    setItems(null);
    try {
      const res = await api.ppsdCompareTime({
        target,
        windows: timeWindows.map((w) => ({
          starttime: toIsoUtc(w.starttime),
          endtime: toIsoUtc(w.endtime),
          label: w.label || undefined,
          color: w.color || undefined,
        })),
        percentiles,
        xaxis,
        yaxis_type: yaxisType,
        show_noise_models: showNoiseModels,
        x_min: axisRange.x_min,
        x_max: axisRange.x_max,
        y_min: axisRange.y_min,
        y_max: axisRange.y_max,
      });
      setImageUrl(res.image_url);
      setItems(res.items);
      setElapsed(res.elapsed_seconds);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <aside className="sidebar">
        <div className="toggle-row">
          <span>Input mode:</span>
          <button
            type="button"
            className={!manualMode ? "active" : ""}
            onClick={() => setManualMode(false)}
          >
            Dropdown
          </button>
          <button
            type="button"
            className={manualMode ? "active" : ""}
            onClick={() => setManualMode(true)}
          >
            Manual
          </button>
        </div>

        <div className="section">
          <h3>Station / channel</h3>
          <p className="hint">비교할 관측소와 채널을 하나만 선택하세요.</p>
          <TargetListEditor
            rows={rows}
            onChange={setRows}
            singleChannel
            singleStation
            manualMode={manualMode}
          />
        </div>

        <TimeWindowListEditor rows={timeWindows} onChange={setTimeWindows} />

        <div className="section">
          <h3>Compare options</h3>
          <div className="field">
            <label>Percentiles (comma-separated)</label>
            <input
              type="text"
              value={percentilesText}
              onChange={(e) => setPercentilesText(e.target.value)}
              placeholder="10, 50, 90"
            />
          </div>
          {percentiles.length > 0 && (
            <div className="chip-row">
              {percentiles.map((p) => (
                <span key={p} className="chip">
                  P{p}
                </span>
              ))}
            </div>
          )}
          <div className="field">
            <label>X axis</label>
            <select
              value={xaxis}
              onChange={(e) =>
                setXaxis(e.target.value as "period" | "frequency")
              }
            >
              <option value="period">Period [s]</option>
              <option value="frequency">Frequency [Hz]</option>
            </select>
          </div>
          <div className="field">
            <label>Y axis (데이터 종류)</label>
            <select
              value={yaxisType}
              onChange={(e) => {
                const t = e.target.value as YAxisType;
                const lim = yLimitsForType(t);
                setYaxisType(t);
                setAxisRange((a) => ({
                  ...a,
                  y_min: lim.y_min,
                  y_max: lim.y_max,
                }));
              }}
            >
              {YAXIS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {yaxisSelectLabel(o)}
                </option>
              ))}
            </select>
          </div>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={showNoiseModels}
              onChange={(e) => setShowNoiseModels(e.target.checked)}
            />
            Show Peterson NLNM / NHNM
          </label>
        </div>

        <AxisRangePanel
          value={axisRange}
          onChange={setAxisRange}
          xaxis={xaxis}
        />

        <button
          className="primary"
          type="button"
          disabled={!canSubmit}
          onClick={submit}
        >
          {loading ? "Comparing…" : `Compare Time (${timeWindows.length})`}
        </button>
      </aside>
      <main className="content">
        <div className="result">
          <div className="result-header">
            <div className="result-title">PPSD Compare Time</div>
            {imageUrl && (
              <a
                className="download"
                href={api.imageUrl(imageUrl)}
                download="ppsd_compare_time.png"
              >
                Download PNG
              </a>
            )}
            {elapsed != null && <span className="badge">{elapsed.toFixed(2)}s</span>}
          </div>

          {items && (
            <div className="stats">
              {items.map((item, idx) => (
                <span
                  key={idx}
                  className={`badge ${item.status === "error" ? "badge-error" : ""}`}
                  style={
                    item.target.color
                      ? { borderColor: item.target.color, color: item.target.color }
                      : undefined
                  }
                >
                  {item.target.label ?? `Window ${idx + 1}`}
                  {item.status === "error" ? " ✗" : item.stats?.from_cache ? " (cached)" : ""}
                </span>
              ))}
            </div>
          )}

          {error && <div className="error">{error}</div>}

          <div className="image-frame">
            {loading ? (
              <div className="placeholder">
                <div className="spinner" />
                Computing and comparing PPSDs…
              </div>
            ) : imageUrl ? (
              <img src={api.imageUrl(imageUrl)} alt="PPSD Compare Time" />
            ) : (
              <div className="placeholder">
                Select one station/channel and multiple time windows, then click{" "}
                <strong>Compare Time</strong>.
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
