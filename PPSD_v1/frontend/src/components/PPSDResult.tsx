import { useRef } from "react";
import { PPSDResponse } from "../api/client";
import { PPSDChart } from "./PPSDChart";
import { exportChartPng } from "../charts/exportPng";

interface Props {
  loading: boolean;
  error: string | null;
  result: PPSDResponse | null;
}

export function PPSDResult({ loading, error, result }: Props) {
  const chartWrapRef = useRef<HTMLDivElement>(null);

  const download = () => {
    if (!chartWrapRef.current || !result) return;
    const name = `ppsd_${result.stats.channel_id.replace(/\./g, "_")}.png`;
    exportChartPng(chartWrapRef.current, name);
  };

  return (
    <div className="result">
      <div className="result-header">
        <div className="result-title">PPSD Plot</div>
        {result && (
          <button type="button" className="download" onClick={download}>
            Download PNG
          </button>
        )}
      </div>

      {result && (
        <div className="stats">
          <span className="badge">{result.stats.channel_id}</span>
          <span className="badge">{result.stats.segments_used} segments</span>
          {result.stats.sampling_rate && (
            <span className="badge">{result.stats.sampling_rate} Hz</span>
          )}
          <span className="badge">
            {new Date(result.stats.starttime).toISOString().slice(0, 19)}Z →{" "}
            {new Date(result.stats.endtime).toISOString().slice(0, 19)}Z
          </span>
          {result.stats.from_cache && <span className="badge">cached</span>}
        </div>
      )}

      {error && <div className="error">{error}</div>}

      <div className="image-frame">
        {loading ? (
          <div className="placeholder">
            <div className="spinner" />
            Computing PPSD… (this can take up to a couple of minutes for long
            windows)
          </div>
        ) : result ? (
          <div ref={chartWrapRef} style={{ width: "100%" }}>
            <PPSDChart data={result.data} />
          </div>
        ) : (
          <div className="placeholder">
            Configure the station, time window and options in the sidebar and
            click <strong>Compute PPSD</strong>.
          </div>
        )}
      </div>
    </div>
  );
}
