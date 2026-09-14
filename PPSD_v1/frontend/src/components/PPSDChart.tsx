import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { HeatmapData } from "../api/client";
import { WebGLQuadLayer } from "../charts/webglHeatmap";
import { buildColormapLut, sampleLut } from "../charts/colormap";
import { useSettings } from "../settings/SettingsContext";

interface Props {
  data: HeatmapData;
  height?: number;
  compact?: boolean;
}

export function PPSDChart({ data, height = 560, compact = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const layerRef = useRef<WebGLQuadLayer | null>(null);
  const { settings } = useSettings();
  const probMin = settings.probability_min;
  const probMax = settings.probability_max;

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    const svgEl = svgRef.current;
    if (!container || !canvas || !svgEl) return;

    const render = () => {
      const totalW = container.clientWidth || 720;
      const totalH = container.clientHeight || height;
      const mobile = totalW < 600;
      const m = compact
        ? mobile
          ? { top: 28, right: 50, bottom: 40, left: 48 }
          : { top: 22, right: 62, bottom: 34, left: 50 }
        : mobile
          ? { top: 42, right: 58, bottom: 48, left: 52 }
          : { top: 34, right: 82, bottom: 46, left: 64 };
      const plotW = Math.max(10, totalW - m.left - m.right);
      const plotH = Math.max(10, totalH - m.top - m.bottom);

      const x = d3
        .scaleLog()
        .domain([data.axis.x_min, data.axis.x_max])
        .range([0, plotW]);
      const y = d3
        .scaleLinear()
        .domain([data.axis.y_min, data.axis.y_max])
        .range([plotH, 0]);

      // ---- WebGL histogram cells ----
      const lut = buildColormapLut(data.cmap);
      const positions: number[] = [];
      const colors: number[] = [];
      const xe = data.x_edges;
      const de = data.db_edges;
      const hist = data.histogram;
      const vmin = Number.isFinite(probMin) ? probMin : 0;
      const vmax =
        Number.isFinite(probMax) && probMax > vmin ? probMax : vmin + 30;
      const span = vmax - vmin;
      for (let i = 0; i < hist.length; i++) {
        const x0 = xe[i];
        const x1 = xe[i + 1];
        if (x0 <= 0 || x1 <= 0) continue;
        const px0 = x(x0);
        const px1 = x(x1);
        const xl = Math.min(px0, px1);
        const xr = Math.max(px0, px1);
        const row = hist[i];
        for (let j = 0; j < row.length; j++) {
          const v = row[j];
          if (v == null || !isFinite(v) || v <= 0) continue;
          const py0 = y(de[j]);
          const py1 = y(de[j + 1]);
          const yt = Math.min(py0, py1);
          const yb = Math.max(py0, py1);
          const t = Math.max(0, Math.min(1, (v - vmin) / span));
          const idx = Math.max(0, Math.min(255, Math.round(t * 255)));
          const r = lut[idx * 3];
          const g = lut[idx * 3 + 1];
          const b = lut[idx * 3 + 2];
          positions.push(xl, yt, xr, yt, xr, yb, xl, yt, xr, yb, xl, yb);
          for (let k = 0; k < 6; k++) colors.push(r, g, b);
        }
      }

      if (!layerRef.current) layerRef.current = new WebGLQuadLayer(canvas);
      canvas.style.left = `${m.left}px`;
      canvas.style.top = `${m.top}px`;
      layerRef.current.draw(
        new Float32Array(positions),
        new Float32Array(colors),
        plotW,
        plotH
      );

      // ---- SVG overlay ----
      const svg = d3.select(svgEl);
      svg.selectAll("*").remove();
      svg.attr("width", totalW).attr("height", totalH);

      const defs = svg.append("defs");
      const clipId = `clip-${Math.random().toString(36).slice(2)}`;
      defs
        .append("clipPath")
        .attr("id", clipId)
        .append("rect")
        .attr("width", plotW)
        .attr("height", plotH);

      const g = svg
        .append("g")
        .attr("transform", `translate(${m.left},${m.top})`);

      g.append("g")
        .attr("class", "grid")
        .call(
          d3
            .axisLeft(y)
            .ticks(8)
            .tickSize(-plotW)
            .tickFormat(() => "") as any
        );
      g.append("g")
        .attr("class", "grid")
        .attr("transform", `translate(0,${plotH})`)
        .call(
          d3
            .axisBottom(x)
            .ticks(6, "~g")
            .tickSize(-plotH)
            .tickFormat(() => "") as any
        );

      g.append("g")
        .attr("class", "axis")
        .attr("transform", `translate(0,${plotH})`)
        .call(d3.axisBottom(x).ticks(6, "~g") as any);
      g.append("g")
        .attr("class", "axis")
        .call(d3.axisLeft(y).ticks(8) as any);

      g.append("text")
        .attr("class", "axis-label")
        .attr("x", plotW / 2)
        .attr("y", plotH + 34)
        .attr("text-anchor", "middle")
        .text(data.xlabel);
      g.append("text")
        .attr("class", "axis-label")
        .attr("transform", "rotate(-90)")
        .attr("x", -plotH / 2)
        .attr("y", -m.left + 14)
        .attr("text-anchor", "middle")
        .text(data.ylabel);
      svg
        .append("text")
        .attr("class", "chart-title")
        .attr("x", totalW / 2)
        .attr("y", 15)
        .attr("text-anchor", "middle")
        .text(data.title);

      const line = d3
        .line<[number, number]>()
        .x((d) => x(d[0]))
        .y((d) => y(d[1]));
      const drawCurve = (
        xs: number[],
        dbs: number[],
        stroke: string,
        dash?: string,
        width = 1.5
      ) => {
        const pts: [number, number][] = [];
        for (let i = 0; i < xs.length; i++) {
          if (xs[i] > 0) pts.push([xs[i], dbs[i]]);
        }
        g.append("path")
          .attr("clip-path", `url(#${clipId})`)
          .attr("fill", "none")
          .attr("stroke", stroke)
          .attr("stroke-width", width)
          .attr("stroke-dasharray", dash ?? null)
          .attr("d", line(pts));
      };

      const legend: { label: string; color: string; dash?: string }[] = [];
      if (data.noise_models) {
        drawCurve(data.noise_models.low.x, data.noise_models.low.db, "#888", "5,3", 1.2);
        drawCurve(data.noise_models.high.x, data.noise_models.high.db, "#888", "5,3", 1.2);
        legend.push({ label: data.noise_models.low.label, color: "#888", dash: "5,3" });
        legend.push({ label: data.noise_models.high.label, color: "#888", dash: "5,3" });
      }
      const ov = data.overlays;
      if (ov.percentile_low) {
        drawCurve(ov.percentile_low.x, ov.percentile_low.db, "#e74c3c");
        legend.push({ label: `P${ov.percentile_low.perc}`, color: "#e74c3c" });
      }
      if (ov.percentile_high) {
        drawCurve(ov.percentile_high.x, ov.percentile_high.db, "#e74c3c");
        legend.push({ label: `P${ov.percentile_high.perc}`, color: "#e74c3c" });
      }
      if (ov.mode) {
        drawCurve(ov.mode.x, ov.mode.db, "#1abc9c");
        legend.push({ label: "mode", color: "#1abc9c" });
      }
      if (ov.mean) {
        drawCurve(ov.mean.x, ov.mean.db, "#f39c12");
        legend.push({ label: "mean", color: "#f39c12" });
      }

      const lg = g.append("g").attr("transform", `translate(${plotW - 8},10)`);
      legend.forEach((it, i) => {
        const row = lg.append("g").attr("transform", `translate(0,${i * 14})`);
        row
          .append("line")
          .attr("x1", -24)
          .attr("x2", -6)
          .attr("y1", 0)
          .attr("y2", 0)
          .attr("stroke", it.color)
          .attr("stroke-width", 1.6)
          .attr("stroke-dasharray", it.dash ?? null);
        row
          .append("text")
          .attr("x", -28)
          .attr("y", 3)
          .attr("text-anchor", "end")
          .attr("class", "legend-text")
          .text(it.label);
      });

      // ---- colorbar ----
      const cbW = 12;
      const cbX = m.left + plotW + 16;
      const cbY = m.top;
      const cbH = plotH;
      const cbId = `cb-${Math.random().toString(36).slice(2)}`;
      const grad = defs
        .append("linearGradient")
        .attr("id", cbId)
        .attr("x1", "0")
        .attr("y1", "1")
        .attr("x2", "0")
        .attr("y2", "0");
      const stops = 16;
      for (let s = 0; s <= stops; s++) {
        const t = s / stops;
        grad
          .append("stop")
          .attr("offset", `${t * 100}%`)
          .attr("stop-color", sampleLut(lut, t));
      }
      svg
        .append("rect")
        .attr("x", cbX)
        .attr("y", cbY)
        .attr("width", cbW)
        .attr("height", cbH)
        .attr("fill", `url(#${cbId})`)
        .attr("stroke", "#8888");
      const cbScale = d3
        .scaleLinear()
        .domain([vmin, vmax])
        .range([cbY + cbH, cbY]);
      svg
        .append("g")
        .attr("class", "axis")
        .attr("transform", `translate(${cbX + cbW},0)`)
        .call(d3.axisRight(cbScale).ticks(5) as any);
      svg
        .append("text")
        .attr("class", "axis-label")
        .attr("transform", "rotate(-90)")
        .attr("x", -(cbY + cbH / 2))
        .attr("y", cbX + cbW + 40)
        .attr("text-anchor", "middle")
        .text("Probability [%]");
    };

    render();
    const ro = new ResizeObserver(() => render());
    ro.observe(container);
    window.addEventListener("resize", render);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", render);
    };
  }, [data, height, compact, probMin, probMax]);

  return (
    <div
      ref={containerRef}
      className={`chart-container ${compact ? "compact-chart" : "full-chart"}`}
      style={{
        position: "relative",
        width: "100%",
        ...(compact ? { height } : undefined),
      }}
    >
      <canvas ref={canvasRef} style={{ position: "absolute" }} />
      <svg
        ref={svgRef}
        style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none" }}
      />
    </div>
  );
}
