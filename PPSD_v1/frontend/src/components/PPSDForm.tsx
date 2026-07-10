import { StationPicker, StationSelection } from "./StationPicker";
import { PlotOptionsPanel, PlotOptionsValue } from "./PlotOptionsPanel";

export interface PPSDFormValue {
  station: StationSelection;
  starttime: string;
  endtime: string;
}

export type PPSDFormState = PPSDFormValue & PlotOptionsValue;

interface Props {
  value: PPSDFormState;
  onChange: (v: PPSDFormState) => void;
  onSubmit: () => void;
  loading: boolean;
}

export function PPSDForm({ value, onChange, onSubmit, loading }: Props) {
  const setStation = (station: StationSelection) =>
    onChange({ ...value, station });
  const setPlot = (plot: PlotOptionsValue) => onChange({ ...value, ...plot });

  const canSubmit =
    !!value.station.network &&
    !!value.station.station &&
    !!value.station.channel &&
    !!value.starttime &&
    !!value.endtime &&
    value.percentile_low < value.percentile_high &&
    !loading;

  const setTime = (k: "starttime" | "endtime", v: string) =>
    onChange({ ...value, [k]: v });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) onSubmit();
      }}
    >
      <StationPicker value={value.station} onChange={setStation} />

      <div className="section">
        <h3>Time window (UTC)</h3>
        <div className="row-2">
          <div className="field">
            <label>Start</label>
            <input
              type="datetime-local"
              step={1}
              value={value.starttime}
              onChange={(e) => setTime("starttime", e.target.value)}
            />
          </div>
          <div className="field">
            <label>End</label>
            <input
              type="datetime-local"
              step={1}
              value={value.endtime}
              onChange={(e) => setTime("endtime", e.target.value)}
            />
          </div>
        </div>
      </div>

      <PlotOptionsPanel value={value} onChange={setPlot} />

      <button className="primary" type="submit" disabled={!canSubmit}>
        {loading ? "Computing…" : "Compute PPSD"}
      </button>
    </form>
  );
}
