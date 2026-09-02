import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import type { ResponseCurve } from "../api";

const WIDTH_MIN = 480;
const HEIGHT = 460;
const MARGIN = { top: 16, right: 20, bottom: 36, left: 58 };
const GAP = 18;

function logTicks(min: number, max: number): number[] {
  const ticks: number[] = [];
  const start = Math.floor(Math.log10(min));
  const end = Math.ceil(Math.log10(max));
  for (let exp = start; exp <= end; exp += 1) {
    const value = 10 ** exp;
    if (value >= min * 0.999 && value <= max * 1.001) ticks.push(value);
  }
  return ticks.length ? ticks : [min, max];
}

function linTicks(min: number, max: number, count = 5): number[] {
  if (max === min) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, i) => min + step * i);
}

function formatTick(value: number): string {
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 0.01 || abs >= 10000)) return value.toExponential(0);
  if (abs >= 100) return value.toFixed(0);
  if (Number.isInteger(value)) return String(value);
  return value.toPrecision(3);
}

function clampLog(value: number): number {
  return Math.max(value, 1e-18);
}

function pathFrom(
  xs: number[],
  ys: number[],
  xOf: (v: number) => number,
  yOf: (v: number) => number
): string {
  return xs
    .map((x, i) => `${i === 0 ? "M" : "L"}${xOf(x).toFixed(2)},${yOf(ys[i]).toFixed(2)}`)
    .join(" ");
}

export function ResponseCurveChart({ curve }: { curve: ResponseCurve }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      setWidth(Math.max(host.clientWidth, WIDTH_MIN));
    });
    observer.observe(host);
    setWidth(Math.max(host.clientWidth, WIDTH_MIN));
    return () => observer.disconnect();
  }, []);

  const plot = useMemo(() => {
    const freqs = curve.frequencies;
    const amps = curve.amplitude.map(clampLog);
    const phases = curve.phase_deg;
    const plotWidth = width - MARGIN.left - MARGIN.right;
    const plotHeight = (HEIGHT - MARGIN.top - MARGIN.bottom - GAP) / 2;
    const xMin = freqs[0];
    const xMax = freqs[freqs.length - 1];
    const yAmpMin = Math.min(...amps);
    const yAmpMax = Math.max(...amps);
    const yPhaseMin = Math.min(-180, ...phases);
    const yPhaseMax = Math.max(180, ...phases);
    const xOf = (f: number) =>
      (Math.log10(f) - Math.log10(xMin)) / (Math.log10(xMax) - Math.log10(xMin)) * plotWidth;
    const yAmpOf = (a: number) => {
      const lo = Math.log10(yAmpMin);
      const hi = Math.log10(yAmpMax === yAmpMin ? yAmpMin * 10 : yAmpMax);
      return plotHeight - ((Math.log10(a) - lo) / (hi - lo)) * plotHeight;
    };
    const yPhaseOf = (p: number) =>
      plotHeight - ((p - yPhaseMin) / (yPhaseMax - yPhaseMin)) * plotHeight;
    return {
      plotWidth,
      plotHeight,
      xOf,
      yAmpOf,
      yPhaseOf,
      ampPath: pathFrom(freqs, amps, xOf, yAmpOf),
      phasePath: pathFrom(freqs, phases, xOf, yPhaseOf),
      xTicks: logTicks(xMin, xMax),
      ampTicks: logTicks(yAmpMin, yAmpMax),
      phaseTicks: linTicks(yPhaseMin, yPhaseMax),
    };
  }, [curve, width]);

  const ampTop = MARGIN.top;
  const phaseTop = MARGIN.top + plot.plotHeight + GAP;

  function onMove(event: MouseEvent<SVGRectElement>) {
    const px = event.nativeEvent.offsetX - MARGIN.left;
    const logMin = Math.log10(curve.frequencies[0]);
    const logMax = Math.log10(curve.frequencies[curve.frequencies.length - 1]);
    const target = logMin + (px / plot.plotWidth) * (logMax - logMin);
    let best = 0;
    let bestDist = Infinity;
    curve.frequencies.forEach((freq, index) => {
      const dist = Math.abs(Math.log10(freq) - target);
      if (dist < bestDist) {
        best = index;
        bestDist = dist;
      }
    });
    setHover(best);
  }

  const hoverX =
    hover == null ? null : MARGIN.left + plot.xOf(curve.frequencies[hover]);

  return (
    <div className="curve-chart" ref={hostRef}>
      <svg
        width={width}
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="img"
        aria-label="응답 곡선"
      >
        <Panel
          left={MARGIN.left}
          top={ampTop}
          width={plot.plotWidth}
          height={plot.plotHeight}
          xTicks={plot.xTicks}
          yTicks={plot.ampTicks}
          xOf={plot.xOf}
          yOf={plot.yAmpOf}
          yLabel="진폭"
          path={plot.ampPath}
        />
        <Panel
          left={MARGIN.left}
          top={phaseTop}
          width={plot.plotWidth}
          height={plot.plotHeight}
          xTicks={plot.xTicks}
          yTicks={plot.phaseTicks}
          xOf={plot.xOf}
          yOf={plot.yPhaseOf}
          yLabel="위상 (°)"
          xLabel="주파수 (Hz)"
          path={plot.phasePath}
        />
        {hoverX != null ? (
          <>
            <line
              x1={hoverX}
              x2={hoverX}
              y1={ampTop}
              y2={ampTop + plot.plotHeight}
              className="curve-hover"
            />
            <line
              x1={hoverX}
              x2={hoverX}
              y1={phaseTop}
              y2={phaseTop + plot.plotHeight}
              className="curve-hover"
            />
          </>
        ) : null}
        <rect
          x={MARGIN.left}
          y={ampTop}
          width={plot.plotWidth}
          height={plot.plotHeight * 2 + GAP}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        />
      </svg>
      {hover != null ? (
        <p className="curve-readout mono">
          {curve.frequencies[hover].toPrecision(4)} Hz ·{" "}
          {curve.amplitude[hover].toExponential(3)} ·{" "}
          {curve.phase_deg[hover].toFixed(1)}°
        </p>
      ) : (
        <p className="curve-readout hint">
          {curve.output} · {curve.npts}점 · {curve.min_freq}–{curve.max_freq} Hz
          {curve.input_units && curve.output_units
            ? ` · ${curve.input_units} → ${curve.output_units}`
            : null}
        </p>
      )}
    </div>
  );
}

function Panel({
  left,
  top,
  width,
  height,
  xTicks,
  yTicks,
  xOf,
  yOf,
  yLabel,
  xLabel,
  path,
}: {
  left: number;
  top: number;
  width: number;
  height: number;
  xTicks: number[];
  yTicks: number[];
  xOf: (v: number) => number;
  yOf: (v: number) => number;
  yLabel: string;
  xLabel?: string;
  path: string;
}) {
  return (
    <g transform={`translate(${left},${top})`}>
      <rect width={width} height={height} className="curve-plot" />
      {xTicks.map((tick) => (
        <g key={`x-${tick}`} transform={`translate(${xOf(tick)},${height})`}>
          <line y2={-height} className="curve-grid" />
          <text y={16} textAnchor="middle" className="curve-tick">
            {formatTick(tick)}
          </text>
        </g>
      ))}
      {yTicks.map((tick) => (
        <g key={`y-${tick}`} transform={`translate(0,${yOf(tick)})`}>
          <line x2={width} className="curve-grid" />
          <text x={-8} dy="0.35em" textAnchor="end" className="curve-tick">
            {formatTick(tick)}
          </text>
        </g>
      ))}
      <path d={path} className="curve-line" />
      <text
        transform={`translate(-44,${height / 2}) rotate(-90)`}
        textAnchor="middle"
        className="curve-axis-label"
      >
        {yLabel}
      </text>
      {xLabel ? (
        <text x={width / 2} y={height + 32} textAnchor="middle" className="curve-axis-label">
          {xLabel}
        </text>
      ) : null}
    </g>
  );
}
