import { useEffect, useState } from "react";
import {
  PlotOptionsPanel,
  PlotOptionsValue,
  DEFAULT_PLOT_OPTIONS,
} from "../components/PlotOptionsPanel";
import {
  TargetListEditor,
  StationRow,
  createDefaultRow,
  expandRowsToTargets,
} from "../components/TargetListEditor";
import { BatchResultGrid } from "../components/BatchResultGrid";
import { api, BatchPPSDItem } from "../api/client";
import { mergePlotDefaults, usePlotDefaults } from "../hooks/usePlotDefaults";
import { defaultTimeWindow, toIsoUtc } from "../utils/time";

export function MultiTab() {
  const plotDefaults = usePlotDefaults();
  const { start, end } = defaultTimeWindow();
  const [rows, setRows] = useState<StationRow[]>([createDefaultRow()]);
  const [starttime, setStarttime] = useState(start);
  const [endtime, setEndtime] = useState(end);
  const [options, setOptions] = useState<PlotOptionsValue>(DEFAULT_PLOT_OPTIONS);
  const [manualMode, setManualMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<BatchPPSDItem[] | null>(null);
  const [elapsed, setElapsed] = useState<number | undefined>();

  useEffect(() => {
    if (plotDefaults) {
      setOptions((o) => mergePlotDefaults(o, plotDefaults));
    }
  }, [plotDefaults]);

  const targets = expandRowsToTargets(rows, false);
  const canSubmit =
    targets.length > 0 && !!starttime && !!endtime && !loading;

  const submit = async () => {
    setLoading(true);
    setError(null);
    setItems(null);
    try {
      const res = await api.ppsdBatch({
        targets,
        starttime: toIsoUtc(starttime),
        endtime: toIsoUtc(endtime),
        options,
      });
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
          manualMode={manualMode}
        />

        <div className="section">
          <h3>Time window (UTC)</h3>
          <div className="row-2">
            <div className="field">
              <label>Start</label>
              <input
                type="datetime-local"
                step={1}
                value={starttime}
                onChange={(e) => setStarttime(e.target.value)}
              />
            </div>
            <div className="field">
              <label>End</label>
              <input
                type="datetime-local"
                step={1}
                value={endtime}
                onChange={(e) => setEndtime(e.target.value)}
              />
            </div>
          </div>
        </div>

        <PlotOptionsPanel value={options} onChange={setOptions} />

        <button
          className="primary"
          type="button"
          disabled={!canSubmit}
          onClick={submit}
        >
          {loading ? "Computing…" : `Compute All (${targets.length})`}
        </button>
      </aside>
      <main className="content">
        <BatchResultGrid
          loading={loading}
          error={error}
          items={items}
          elapsed={elapsed}
        />
      </main>
    </>
  );
}
