import { useEffect, useState } from "react";
import { api, PlotDefaults, YAxisType } from "../api/client";

export function usePlotDefaults(): PlotDefaults | null {
  const [defaults, setDefaults] = useState<PlotDefaults | null>(null);
  useEffect(() => {
    api.plotDefaults().then(setDefaults).catch(() => {});
  }, []);
  return defaults;
}

export function mergePlotDefaults<T extends {
  x_min?: number | null;
  x_max?: number | null;
  y_min?: number | null;
  y_max?: number | null;
  yaxis_type?: YAxisType;
}>(base: T, defaults: PlotDefaults | null): T {
  if (!defaults) return base;
  return {
    ...base,
    x_min: base.x_min ?? defaults.x_min ?? null,
    x_max: base.x_max ?? defaults.x_max ?? null,
    y_min: base.y_min ?? defaults.y_min ?? null,
    y_max: base.y_max ?? defaults.y_max ?? null,
    yaxis_type: base.yaxis_type ?? defaults.yaxis_type ?? "acceleration",
  };
}
