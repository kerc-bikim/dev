import { useEffect, useRef, useState } from "react";
import {
  TargetListEditor,
  StationRow,
  createDefaultRow,
  expandRowsToTargets,
} from "../components/TargetListEditor";
import { AxisRangePanel, EMPTY_AXIS_RANGE, AxisRangeValue } from "../components/AxisRangePanel";
import { api, BatchPPSDItem, CompareData, YAxisType } from "../api/client";
import { CompareChart } from "../components/CompareChart";
import { exportChartPng } from "../charts/exportPng";
import { mergePlotDefaults, usePlotDefaults } from "../hooks/usePlotDefaults";
import {
  yLimitsForType,
  YAXIS_OPTIONS,
  yaxisSelectLabel,
  yaxisTypeForChannels,
} from "../utils/yaxisDefaults";
import { channelId, defaultTimeWindow, toIsoUtc } from "../utils/time";
import { useSettings } from "../settings/SettingsContext";

export function CompareStationTab() {
  const plotDefaults = usePlotDefaults();
  const { settings } = useSettings();
  const { start, end } = defaultTimeWindow();
  const [rows, setRows] = useState<StationRow[]>([
    createDefaultRow(true),
    { ...createDefaultRow(true), color: "#3498db" },
  ]);
  const [starttime, setStarttime] = useState(start);
  const [endtime, setEndtime] = useState(end);
  const [percentilesText, setPercentilesText] = useState(
    settings.compare_percentiles
  );
  const [xaxis, setXaxis] = useState<"period" | "frequency">(settings.xaxis);
  const [yaxisType, setYaxisType] = useState<YAxisType>("acceleration");
  const [showNoiseModels, setShowNoiseModels] = useState(
    settings.show_noise_models
  );
  const [axisRange, setAxisRange] = useState<AxisRangeValue>({
    ...EMPTY_AXIS_RANGE,
    ...yLimitsForType("acceleration"),
  });
  const [manualMode, setManualMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chartData, setChartData] = useState<CompareData | null>(null);
  const [items, setItems] = useState<BatchPPSDItem[] | null>(null);
  const [elapsed, setElapsed] = useState<number | undefined>();
  const chartWrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (plotDefaults) {
      setAxisRange((a) => mergePlotDefaults(a, plotDefaults));
      if (plotDefaults.yaxis_type) {
        setYaxisType(plotDefaults.yaxis_type);
      }
    }
  }, [plotDefaults]);

  const targets = expandRowsToTargets(rows, true);

  // Auto-select Y-axis unit from the selected channels (still overridable).
  const autoYRef = useRef<string>("");
  useEffect(() => {
    const t = yaxisTypeForChannels(targets.map((tg) => tg.channel));
    if (t && t !== autoYRef.current) {
      autoYRef.current = t;
      const lim = yLimitsForType(t);
      setYaxisType(t);
      setAxisRange((a) => ({ ...a, y_min: lim.y_min, y_max: lim.y_max }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  const percentiles = percentilesText
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n) && n >= 0 && n <= 100);

  const canSubmit =
    targets.length >= 1 &&
    percentiles.length >= 1 &&
    !!starttime &&
    !!endtime &&
    !loading;

  const submit = async () => {
    setLoading(true);
    setError(null);
    setChartData(null);
    setItems(null);
    try {
      const res = await api.ppsdCompare({
        targets,
        starttime: toIsoUtc(starttime),
        endtime: toIsoUtc(endtime),
        percentiles,
        xaxis,
        yaxis_type: yaxisType,
        show_noise_models: showNoiseModels,
        x_min: axisRange.x_min,
        x_max: axisRange.x_max,
        y_min: axisRange.y_min,
        y_max: axisRange.y_max,
      });
      setChartData(res.data);
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

        <TargetListEditor
          rows={rows}
          onChange={setRows}
          showColors
          manualMode={manualMode}
        />

        <div className="section">
          <h3>Time window (UTC)</h3>
          <p className="hint">동일한 시간 구간에서 관측소·채널을 비교합니다.</p>
          <div className="row-2">
            <div className="field">
              <label>Start</label>
              <input
                type="datetime-local"
                lang="sv-SE"
                step={1}
                value={starttime}
                onChange={(e) => setStarttime(e.target.value)}
              />
            </div>
            <div className="field">
              <label>End</label>
              <input
                type="datetime-local"
                lang="sv-SE"
                step={1}
                value={endtime}
                onChange={(e) => setEndtime(e.target.value)}
              />
            </div>
          </div>
        </div>

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
          {loading ? "Comparing…" : `Compare Station (${targets.length})`}
        </button>
      </aside>
      <main className="content">
        <div className="result">
          <div className="result-header">
            <div className="result-title">PPSD Compare Station</div>
            {chartData && (
              <button
                type="button"
                className="download"
                onClick={() =>
                  chartWrapRef.current &&
                  exportChartPng(chartWrapRef.current, "ppsd_compare_station.png")
                }
              >
                Download PNG
              </button>
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
                  {channelId(item.target)}
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
            ) : chartData ? (
              <div ref={chartWrapRef} style={{ width: "100%" }}>
                <CompareChart data={chartData} />
              </div>
            ) : (
              <div className="placeholder">
                Select stations for the same time window, then click{" "}
                <strong>Compare Station</strong>.
              </div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
