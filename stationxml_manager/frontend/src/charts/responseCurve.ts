import * as d3 from "d3";

export const OVERLAY_COLORS = [
  "#0072B2",
  "#E69F00",
  "#009E73",
  "#D55E00",
  "#CC79A7",
  "#56B4E9",
  "#F0E442",
  "#000000",
];

export interface CurveSeries {
  nslc: string;
  start_time?: string | null;
  amplitude: number[];
  phase_deg: number[];
}

export interface CurveChartData {
  frequencies: number[];
  series: CurveSeries[];
  output: string;
  title: string;
  errors?: string[];
}

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function legendLabel(item: CurveSeries, all: CurveSeries[]): string {
  const same = all.filter((row) => row.nslc === item.nslc).length > 1;
  if (same && item.start_time) {
    return `${item.nslc} ${item.start_time.slice(0, 10)}`;
  }
  return item.nslc;
}

export function renderResponseCurve(container: HTMLElement, data: CurveChartData): void {
  container.innerHTML = "";
  const width = Math.max(container.clientWidth || 720, 480);
  const height = 520;
  const margin = { top: 48, right: 24, bottom: 36, left: 64 };
  const panelGap = 18;
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = (height - margin.top - margin.bottom - panelGap) / 2;
  const fg = cssVar("--fg", "#e6edf3");
  const muted = cssVar("--muted", "#8b949e");
  const bg = cssVar("--bg", "#0d1117");

  const svg = d3
    .select(container)
    .append("svg")
    .attr("width", width)
    .attr("height", height)
    .attr("viewBox", `0 0 ${width} ${height}`)
    .style("background", bg);

  svg
    .append("text")
    .attr("x", margin.left)
    .attr("y", 22)
    .attr("fill", fg)
    .attr("font-size", 14)
    .text(`${data.title}  (${data.output})`);

  if (data.errors?.length) {
    svg
      .append("text")
      .attr("x", margin.left)
      .attr("y", 38)
      .attr("fill", cssVar("--warn", "#d29922"))
      .attr("font-size", 11)
      .text(data.errors.join(" · "));
  }

  const freqs = data.frequencies;
  if (!freqs.length || !data.series.length) {
    svg
      .append("text")
      .attr("x", width / 2)
      .attr("y", height / 2)
      .attr("text-anchor", "middle")
      .attr("fill", muted)
      .text("그릴 응답 곡선이 없습니다");
    return;
  }

  const x = d3
    .scaleLog()
    .domain([freqs[0], freqs[freqs.length - 1]])
    .range([0, plotWidth]);
  const amps = data.series.flatMap((s) => s.amplitude.filter((v) => v > 0));
  const yAmp = d3
    .scaleLog()
    .domain([
      Math.max(d3.min(amps) || 1e-12, 1e-18),
      Math.max(d3.max(amps) || 1, 1e-12),
    ])
    .range([plotHeight, 0])
    .nice();
  const phases = data.series.flatMap((s) => s.phase_deg);
  const yPhase = d3
    .scaleLinear()
    .domain([
      Math.min(-180, d3.min(phases) ?? -180),
      Math.max(180, d3.max(phases) ?? 180),
    ])
    .range([plotHeight, 0]);

  const gAmp = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
  const gPhase = svg
    .append("g")
    .attr("transform", `translate(${margin.left},${margin.top + plotHeight + panelGap})`);

  const axis = (g: d3.Selection<SVGGElement, unknown, null, undefined>, y: d3.AxisScale<d3.NumberValue>, label: string) => {
    g.append("g")
      .attr("transform", `translate(0,${plotHeight})`)
      .call(d3.axisBottom(x).ticks(6, "~s"))
      .selectAll("text")
      .attr("fill", muted);
    g.append("g").call(d3.axisLeft(y).ticks(5)).selectAll("text").attr("fill", muted);
    g.selectAll("path,line").attr("stroke", muted);
    g.append("text")
      .attr("x", -plotHeight / 2)
      .attr("y", -48)
      .attr("transform", "rotate(-90)")
      .attr("fill", muted)
      .attr("text-anchor", "middle")
      .attr("font-size", 11)
      .text(label);
  };
  axis(gAmp, yAmp, "진폭");
  axis(gPhase, yPhase, "위상 (°)");
  gPhase
    .append("text")
    .attr("x", plotWidth / 2)
    .attr("y", plotHeight + 32)
    .attr("fill", muted)
    .attr("text-anchor", "middle")
    .attr("font-size", 11)
    .text("주파수 (Hz)");

  const lineAmp = d3
    .line<number>()
    .x((_, i) => x(freqs[i]))
    .y((d) => yAmp(Math.max(d, 1e-18)));
  const linePhase = d3
    .line<number>()
    .x((_, i) => x(freqs[i]))
    .y((d) => yPhase(d));

  const ampPaths: d3.Selection<SVGPathElement, unknown, null, undefined>[] = [];
  const phasePaths: d3.Selection<SVGPathElement, unknown, null, undefined>[] = [];
  data.series.forEach((series, index) => {
    const color = OVERLAY_COLORS[index % OVERLAY_COLORS.length];
    ampPaths.push(
      gAmp
        .append("path")
        .attr("fill", "none")
        .attr("stroke", color)
        .attr("stroke-width", 1.6)
        .attr("d", lineAmp(series.amplitude) || "")
    );
    phasePaths.push(
      gPhase
        .append("path")
        .attr("fill", "none")
        .attr("stroke", color)
        .attr("stroke-width", 1.6)
        .attr("d", linePhase(series.phase_deg) || "")
    );
  });

  const tooltip = d3
    .select(container)
    .style("position", "relative")
    .append("div")
    .attr("class", "response-tooltip")
    .style("display", "none");
  const hoverAmp = gAmp
    .append("line")
    .attr("y1", 0)
    .attr("y2", plotHeight)
    .attr("stroke", muted)
    .attr("stroke-dasharray", "3 3")
    .style("display", "none");
  const hoverPhase = gPhase
    .append("line")
    .attr("y1", 0)
    .attr("y2", plotHeight)
    .attr("stroke", muted)
    .attr("stroke-dasharray", "3 3")
    .style("display", "none");

  const setHover = (
    index: number | null,
    clientX = 0,
    clientY = 0,
    nearestSeries: number | null = null
  ) => {
    if (index == null) {
      hoverAmp.style("display", "none");
      hoverPhase.style("display", "none");
      tooltip.style("display", "none");
      ampPaths.forEach((path) => path.attr("opacity", 1).attr("stroke-width", 1.6));
      phasePaths.forEach((path) => path.attr("opacity", 1).attr("stroke-width", 1.6));
      return;
    }
    const freq = freqs[index];
    hoverAmp.attr("x1", x(freq)).attr("x2", x(freq)).style("display", null);
    hoverPhase.attr("x1", x(freq)).attr("x2", x(freq)).style("display", null);
    ampPaths.forEach((path, i) => {
      const active = nearestSeries == null || i === nearestSeries;
      path.attr("opacity", active ? 1 : 0.22).attr("stroke-width", active ? 2.2 : 1.2);
    });
    phasePaths.forEach((path, i) => {
      const active = nearestSeries == null || i === nearestSeries;
      path.attr("opacity", active ? 1 : 0.22).attr("stroke-width", active ? 2.2 : 1.2);
    });
    const lines = data.series.map((series) => {
      const amp = series.amplitude[index];
      const phase = series.phase_deg[index];
      return `${legendLabel(series, data.series)}  ${freq.toPrecision(4)} Hz  ${amp.toExponential(3)}  ${phase.toFixed(1)}°`;
    });
    tooltip
      .style("display", "block")
      .style("left", `${Math.min(clientX + 12, width - 80)}px`)
      .style("top", `${Math.max(clientY - 12, 8)}px`)
      .style("white-space", "pre")
      .text(lines.join("\n"));
  };

  const nearestIndex = (px: number) => {
    const freq = x.invert(px);
    let best = 0;
    let bestDist = Infinity;
    freqs.forEach((value, index) => {
      const dist = Math.abs(Math.log10(value) - Math.log10(freq));
      if (dist < bestDist) {
        best = index;
        bestDist = dist;
      }
    });
    return best;
  };

  const nearestSeriesAt = (index: number, py: number, isAmp: boolean) => {
    let best = 0;
    let bestDist = Infinity;
    data.series.forEach((series, si) => {
      const yVal = isAmp
        ? yAmp(Math.max(series.amplitude[index] || 0, 1e-18))
        : yPhase(series.phase_deg[index]);
      const dist = Math.abs(yVal - py);
      if (dist < bestDist) {
        best = si;
        bestDist = dist;
      }
    });
    return best;
  };

  const bindHover = (
    g: d3.Selection<SVGGElement, unknown, null, undefined>,
    isAmp: boolean
  ) => {
    g.append("rect")
      .attr("width", plotWidth)
      .attr("height", plotHeight)
      .attr("fill", "transparent")
      .on("mousemove", (event: MouseEvent) => {
        const [px, py] = d3.pointer(event);
        const index = nearestIndex(px);
        const [cx, cy] = d3.pointer(event, container);
        setHover(index, cx, cy, nearestSeriesAt(index, py, isAmp));
      })
      .on("mouseleave", () => setHover(null));
  };
  bindHover(gAmp, true);
  bindHover(gPhase, false);

  const legend = svg.append("g").attr("transform", `translate(${width - 220}, 16)`);
  data.series.forEach((series, index) => {
    const y = index * 14;
    legend
      .append("rect")
      .attr("x", 0)
      .attr("y", y)
      .attr("width", 10)
      .attr("height", 3)
      .attr("fill", OVERLAY_COLORS[index % OVERLAY_COLORS.length]);
    legend
      .append("text")
      .attr("x", 16)
      .attr("y", y + 4)
      .attr("fill", fg)
      .attr("font-size", 11)
      .text(legendLabel(series, data.series));
  });
}
