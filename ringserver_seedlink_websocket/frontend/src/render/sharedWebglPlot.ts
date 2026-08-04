import { WebglPlot, type WebglLinePlot, updateViewport } from "webgl-plot";
import { hexToRgba, minMaxDownsampleTimed } from "./downsample";
import { bufferStore } from "../buffer/ringBuffer";
import type { SCNL, WaveformColors, XAxisRightAnchor, YScaleMode } from "../types";
import { scnlKey } from "../types";

export const PANEL_ROW_MIN_PX = 100;

export type PanelSpec = {
  scnl: SCNL;
  /** FFT 모드일 때 웨이브폼 라인 숨김 */
  hideWave?: boolean;
};

export type PanelStats = {
  key: string;
  min: number | null;
  max: number | null;
};

export class SharedWaveformRenderer {
  private plot: WebglPlot | null = null;
  private linePlot: WebglLinePlot | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private points = 1200;
  private scratchX = new Float32Array(2400);
  private scratchY = new Float32Array(2400);
  private pointBufs: Float32Array[] = [];
  private lastPanels: PanelSpec[] = [];
  private lastColors: WaveformColors | null = null;
  private lastStats: PanelStats[] = [];

  attach(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.plot = new WebglPlot(canvas, {
      antialias: false,
      powerPerformance: "high-performance",
      backgroundColor: [0.07, 0.09, 0.12, 1],
    });
    this.resize();
  }

  dispose() {
    try {
      this.linePlot?.cleanup();
    } catch {
      /* ignore */
    }
    this.linePlot = null;
    this.plot = null;
    this.canvas = null;
    this.pointBufs = [];
    this.lastPanels = [];
    this.lastColors = null;
    this.lastStats = [];
  }

  getLastStats() {
    return this.lastStats;
  }

  /** 스크롤 콘텐츠 높이에 맞춰 canvas/viewport 재구성 */
  resize(rebuildLines = true) {
    if (!this.canvas || !this.plot) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const parent = this.canvas.parentElement;
    const scrollHost = parent?.parentElement;
    const w = Math.max(1, parent?.clientWidth || this.canvas.clientWidth || 800);
    const viewH = Math.max(1, scrollHost?.clientHeight || parent?.clientHeight || 400);
    const rows = this.lastPanels.length;
    const contentH =
      rows === 0 ? viewH : Math.max(viewH, rows * PANEL_ROW_MIN_PX);

    if (parent) {
      parent.style.height = `${contentH}px`;
      parent.style.minHeight = `${contentH}px`;
    }

    this.canvas.style.width = "100%";
    this.canvas.style.height = "100%";
    this.canvas.width = Math.floor(w * dpr);
    this.canvas.height = Math.floor(contentH * dpr);

    try {
      updateViewport(this.plot.gl, this.canvas);
    } catch {
      this.plot.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }

    const nextPoints = Math.max(200, Math.floor(w));
    const pointsChanged = nextPoints !== this.points;
    this.points = nextPoints;
    this.scratchX = new Float32Array(this.points * 2);
    this.scratchY = new Float32Array(this.points * 2);

    if (rebuildLines && this.lastColors && (pointsChanged || this.pointBufs.length !== this.lastPanels.length)) {
      this.setPanels(this.lastPanels, this.lastColors);
    }
  }

  setPanels(panels: PanelSpec[], colors: WaveformColors) {
    if (!this.plot || !this.canvas) return;
    this.lastPanels = panels;
    this.lastColors = colors;
    this.resize(false);
    try {
      this.linePlot?.cleanup();
    } catch {
      /* ignore */
    }
    const maxLines = Math.max(1, panels.length);
    this.linePlot = this.plot.newThinLinePlotter(maxLines);
    this.pointBufs = panels.map(() => new Float32Array(this.points * 2));

    const configs = panels.map((p, idx) => {
      const hex =
        colors.channelColorMap[scnlKey(p.scnl)] ||
        colors.palette[idx % colors.palette.length] ||
        "#3dd6c6";
      const c = hexToRgba(hex);
      const pts = this.pointBufs[idx]!;
      for (let i = 0; i < this.points; i++) {
        const x = -1 + (2 * i) / Math.max(1, this.points - 1);
        pts[i * 2] = x;
        pts[i * 2 + 1] = 0;
      }
      return {
        points: pts,
        color: [c.r, c.g, c.b, c.a] as [number, number, number, number],
        thickness: 1,
        enabled: true,
      };
    });
    this.linePlot.initLines(configs);
  }

  draw(
    panels: PanelSpec[],
    durationSec: number,
    amplitudeMode: "raw" | "physical",
    windowEndMs: number,
    _anchor?: XAxisRightAnchor,
    yScaleMode: YScaleMode = "auto",
  ) {
    if (!this.plot || !this.linePlot) return;
    const n = Math.max(1, panels.length);
    const rowH = 2 / n;
    const yHalf = rowH * 0.38;
    const stats: PanelStats[] = [];

    type Prepared = {
      idx: number;
      pts: Float32Array;
      yBase: number;
      mid: number;
      amp: number;
      samples: Float32Array;
      sampleStartMs: number;
      sampleRate: number;
      windowStartMs: number;
      windowEndMs: number;
    };
    const prepared: Prepared[] = [];
    let uniformAmp = 0;

    const fillFlat = (pts: Float32Array, yBase: number) => {
      for (let i = 0; i < this.points; i++) {
        pts[i * 2] = -1 + (2 * i) / Math.max(1, this.points - 1);
        pts[i * 2 + 1] = yBase;
      }
    };
    /** 데이터 없을 때 화면 밖으로 밀어 평탄선이 보이지 않게 함 */
    const fillHidden = (pts: Float32Array, yBase: number) => {
      for (let i = 0; i < this.points; i++) {
        pts[i * 2] = -2;
        pts[i * 2 + 1] = yBase;
      }
    };

    // 1) 패널별 min/max·amp 수집 (Uniform이면 최대 amp를 공통 스케일로 사용)
    panels.forEach((panel, idx) => {
      const key = scnlKey(panel.scnl);
      const buf = bufferStore.get(key);
      const pts = this.pointBufs[idx];
      if (!pts) return;
      const yBase = 1 - rowH * (idx + 0.5);

      if (!buf || panel.hideWave) {
        if (panel.hideWave) fillFlat(pts, yBase);
        else fillHidden(pts, yBase);
        this.linePlot!.updateLinePoints(idx, pts);
        stats.push({ key, min: null, max: null });
        return;
      }

      const win = buf.copyAlignedWindow(windowEndMs, durationSec);
      let samples = win.samples;
      if (amplitudeMode === "physical" && buf.sensitivity && buf.sensitivity !== 0) {
        const scaled = new Float32Array(samples.length);
        for (let i = 0; i < samples.length; i++) scaled[i] = samples[i]! / buf.sensitivity!;
        samples = scaled;
      }

      if (samples.length === 0) {
        fillHidden(pts, yBase);
        this.linePlot!.updateLinePoints(idx, pts);
        stats.push({ key, min: null, max: null });
        return;
      }

      let min = Infinity;
      let max = -Infinity;
      for (let i = 0; i < samples.length; i++) {
        const v = samples[i]!;
        if (v < min) min = v;
        if (v > max) max = v;
      }
      if (!Number.isFinite(min) || !Number.isFinite(max)) {
        fillHidden(pts, yBase);
        this.linePlot!.updateLinePoints(idx, pts);
        stats.push({ key, min: null, max: null });
        return;
      }
      stats.push({ key, min, max });
      let lo = min;
      let hi = max;
      if (lo === hi) {
        lo -= 1;
        hi += 1;
      }

      const mid = (hi + lo) / 2;
      const amp = ((hi - lo) / 2) * 1.08 || 1;
      if (amp > uniformAmp) uniformAmp = amp;

      prepared.push({
        idx,
        pts,
        yBase,
        mid,
        amp,
        samples,
        sampleStartMs: win.sampleStartMs,
        sampleRate: win.sampleRate,
        windowStartMs: win.windowStartMs,
        windowEndMs: win.windowEndMs,
      });
    });

    const sharedAmp =
      yScaleMode === "uniform" && uniformAmp > 0 ? uniformAmp : null;

    // 2) 스케일 적용 후 라인 업로드
    for (const p of prepared) {
      const amp = sharedAmp ?? p.amp;
      const yScale = yHalf / amp;
      const yTop = p.yBase + yHalf;
      const yBot = p.yBase - yHalf;

      const count = minMaxDownsampleTimed(
        p.samples,
        p.sampleStartMs,
        p.sampleRate,
        p.windowStartMs,
        p.windowEndMs,
        this.scratchY,
        this.scratchX,
        this.points,
      );
      const used = Math.min(count, this.points);
      if (used <= 0) {
        fillHidden(p.pts, p.yBase);
        this.linePlot!.updateLinePoints(p.idx, p.pts);
        continue;
      }

      for (let i = 0; i < used; i++) {
        const x = -1 + 2 * (this.scratchX[i] ?? 0);
        let y = p.yBase + (this.scratchY[i]! - p.mid) * yScale;
        if (y > yTop) y = yTop;
        if (y < yBot) y = yBot;
        p.pts[i * 2] = x;
        p.pts[i * 2 + 1] = y;
      }

      const lx = p.pts[(used - 1) * 2]!;
      const ly = p.pts[(used - 1) * 2 + 1]!;
      for (let i = used; i < this.points; i++) {
        p.pts[i * 2] = lx;
        p.pts[i * 2 + 1] = ly;
      }

      this.linePlot!.updateLinePoints(p.idx, p.pts);
    }

    this.lastStats = stats;
    this.plot.clear();
    this.linePlot.draw();
    this.plot.update();
  }
}
