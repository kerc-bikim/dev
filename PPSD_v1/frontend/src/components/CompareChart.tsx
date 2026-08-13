import { useEffect, useRef } from "react";
import * as d3 from "d3";
import { CompareData } from "../api/client";

interface Props {
  data: CompareData;
  height?: number;
}

const DASHES = [null, "6,3", "2,3", "6,3,2,3"];

export function CompareChart({ data, height = 560 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    const svgEl = svgRef.current;
    if (!container || !svgEl) return;

    const render = () => {
      const totalW = container.clientWidth || 720;
      const totalH = height;
      const m = { top: 34, right: 24, bottom: 46, left: 64 };
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
        dash: string | null,
        width = 1.6
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
          .attr("stroke-dasharray", dash)
          .attr("d", line(pts));
      };

      const legend: { label: string; color: string; dash?: string | null }[] = [];
      data.series.forEach((s) => {
        s.curves.forEach((c, ci) => {
          drawCurve(c.x, c.db, s.color, DASHES[ci % DASHES.length]);
        });
        legend.push({ label: s.label, color: s.color });
      });

      if (data.noise_models) {
        drawCurve(data.noise_models.low.x, data.noise_models.low.db, "#888", "5,3", 1.2);
        drawCurve(data.noise_models.high.x, data.noise_models.high.db, "#888", "5,3", 1.2);
        legend.push({ label: data.noise_models.low.label, color: "#888", dash: "5,3" });
        legend.push({ label: data.noise_models.high.label, color: "#888", dash: "5,3" });
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
          .attr("stroke-width", 1.8)
          .attr("stroke-dasharray", it.dash ?? null);
        row
          .append("text")
          .attr("x", -28)
          .attr("y", 3)
          .attr("text-anchor", "end")
          .attr("class", "legend-text")
          .text(it.label);
      });
    };

    render();
    const ro = new ResizeObserver(() => render());
    ro.observe(container);
    return () => ro.disconnect();
  }, [data, height]);

  return (
    <div
      ref={containerRef}
      className="chart-container"
      style={{ position: "relative", width: "100%", height }}
    >
      <svg ref={svgRef} style={{ position: "absolute", left: 0, top: 0 }} />
    </div>
  );
}
