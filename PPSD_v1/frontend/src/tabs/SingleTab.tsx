import { useEffect, useState } from "react";
import { PPSDForm, PPSDFormState } from "../components/PPSDForm";
import { PPSDResult } from "../components/PPSDResult";
import { DEFAULT_PLOT_OPTIONS } from "../components/PlotOptionsPanel";
import { api, PPSDRequestBody, PPSDResponse } from "../api/client";
import { mergePlotDefaults, usePlotDefaults } from "../hooks/usePlotDefaults";
import { defaultTimeWindow, toIsoUtc } from "../utils/time";

const initialForm = (): PPSDFormState => {
  const { start, end } = defaultTimeWindow();
  return {
    station: { network: "", station: "", location: "", channel: "" },
    starttime: start,
    endtime: end,
    ...DEFAULT_PLOT_OPTIONS,
  };
};

export function SingleTab() {
  const plotDefaults = usePlotDefaults();
  const [form, setForm] = useState<PPSDFormState>(initialForm());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PPSDResponse | null>(null);

  useEffect(() => {
    if (plotDefaults) {
      setForm((f) => mergePlotDefaults(f, plotDefaults));
    }
  }, [plotDefaults]);

  const submit = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const body: PPSDRequestBody = {
        network: form.station.network,
        station: form.station.station,
        location: form.station.location,
        channel: form.station.channel,
        starttime: toIsoUtc(form.starttime),
        endtime: toIsoUtc(form.endtime),
        percentile_low: form.percentile_low,
        percentile_high: form.percentile_high,
        show_overlay: form.show_overlay,
        clip_to_percentile: form.clip_to_percentile,
        xaxis: form.xaxis,
        yaxis_type: form.yaxis_type,
        show_noise_models: form.show_noise_models,
        show_mean: form.show_mean,
        show_mode: form.show_mode,
        cmap: form.cmap,
        x_min: form.x_min,
        x_max: form.x_max,
        y_min: form.y_min,
        y_max: form.y_max,
      };
      const res = await api.ppsd(body);
      setResult(res);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <aside className="sidebar">
        <PPSDForm
          value={form}
          onChange={setForm}
          onSubmit={submit}
          loading={loading}
        />
      </aside>
      <main className="content">
        <PPSDResult loading={loading} error={error} result={result} />
      </main>
    </>
  );
}
