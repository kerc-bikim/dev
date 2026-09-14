import { useEffect, useMemo, useRef, useState } from "react";
import { DateTime } from "luxon";
import { useAppStore } from "../../store/appStore";
import { SharedWaveformRenderer, PANEL_ROW_MIN_PX } from "../../render/sharedWebglPlot";
import { PanelFftCanvas } from "./PanelFftCanvas";
import { PanelSpectrogramCanvas } from "./PanelSpectrogramCanvas";
import type { SCNL, XAxisRightAnchor } from "../../types";
import { scnlKey } from "../../types";
import { bufferStore, resolveWindowEndMs } from "../../buffer/ringBuffer";
import { buildTimeAxisTicks, type TimeAxisTick } from "../../realtime/timeWindow";
import { resolveBandPass } from "../../realtime/bandPassPresets";
import { applyBandPassCached } from "../../render/bandpass";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/theme/ThemeProvider";
import { getThemeWaveformColors, readPlotBackgroundHex } from "@/theme/theme";

type PanelOverlay = {
  key: string;
  scnl: SCNL;
  gapCount: number;
  rangeLabel: string;
  hasData: boolean;
};

type TimeAxisLabels = {
  startLabel: string;
  endLabel: string;
  ticks: TimeAxisTick[];
};

type ViewWindow = {
  startMs: number;
  endMs: number;
};

/** 우클릭 순환: 웨이브폼 → FFT → Spectrogram */
type AnalysisMode = "fft" | "spec";

const MIN_ZOOM_SEC = 0.5;
const ZOOM_DRAG_THRESHOLD_PX = 6;
const ZOOM_DBLCLICK_MS = 350;
const TAP_MAX_MOVE_PX = 12;
const PINCH_MIN_DIST_PX = 16;

function clampViewToBase(view: ViewWindow, base: ViewWindow): ViewWindow {
  const baseDur = Math.max(1, base.endMs - base.startMs);
  let dur = Math.max(MIN_ZOOM_SEC * 1000, view.endMs - view.startMs);
  if (dur >= baseDur - 1) return { startMs: base.startMs, endMs: base.endMs };
  let startMs = view.startMs;
  let endMs = startMs + dur;
  if (startMs < base.startMs) {
    startMs = base.startMs;
    endMs = startMs + dur;
  }
  if (endMs > base.endMs) {
    endMs = base.endMs;
    startMs = endMs - dur;
  }
  return { startMs, endMs };
}

function viewsNearlyEqual(a: ViewWindow, b: ViewWindow, eps = 2): boolean {
  return (
    Math.abs(a.startMs - b.startMs) <= eps && Math.abs(a.endMs - b.endMs) <= eps
  );
}

type PointerSample = { x: number; y: number; type: string };
type Gesture =
  | {
      kind: "box-zoom";
      pointerId: number;
      startX: number;
      curX: number;
      moved: boolean;
    }
  | {
      kind: "pan";
      pointerId: number;
      startClientX: number;
      origin: ViewWindow;
    }
  | {
      kind: "pinch";
      id0: number;
      id1: number;
      startDist: number;
      origin: ViewWindow;
      centerRatio: number;
    };

/** 모니터 스타일: STA [LOC] CHA NET */
function scnlBadge(s: SCNL): string {
  const loc = !s.location || s.location === "--" ? "" : s.location;
  return loc
    ? `${s.station} ${loc} ${s.channel} ${s.network}`
    : `${s.station} ${s.channel} ${s.network}`;
}

function fmtHms(ms: number): string {
  if (!ms || !Number.isFinite(ms)) return "--:--:--";
  return DateTime.fromMillis(ms).toFormat("HH:mm:ss");
}

function fmtAmp(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1000) return v.toFixed(0);
  if (a >= 1) return v.toFixed(1);
  if (a >= 0.01) return v.toFixed(3);
  return v.toExponential(2);
}

function amplitudeUnit(
  mode: "raw" | "physical",
  inputUnits: string | null | undefined,
  hasPhysicalScale: boolean,
): string {
  if (mode === "raw" || !hasPhysicalScale) return "counts";
  const u = (inputUnits || "").trim();
  return u || "counts";
}

function viewDurationSec(v: ViewWindow): number {
  return Math.max(MIN_ZOOM_SEC, (v.endMs - v.startMs) / 1000);
}

function buildOverlays(
  panels: { scnl: SCNL }[],
  view: ViewWindow,
  amplitudeMode: "raw" | "physical",
  stats?: { key: string; min: number | null; max: number | null }[],
  bandPass?: { fminHz: number; fmaxHz: number } | null,
): { overlays: PanelOverlay[]; timeAxis: TimeAxisLabels } {
  const durationSec = viewDurationSec(view);
  const ticks = buildTimeAxisTicks(view.startMs, view.endMs, durationSec);
  const timeAxis: TimeAxisLabels = {
    startLabel: fmtHms(view.startMs),
    endLabel: fmtHms(view.endMs),
    ticks,
  };
  const statsMap = new Map((stats || []).map((s) => [s.key, s]));

  const overlays = panels.map((p) => {
    const key = scnlKey(p.scnl);
    const buf = bufferStore.get(key);
    const gaps = buf?.gapsInWindow(durationSec, view.endMs) || [];
    const canPhysical =
      amplitudeMode === "physical" && !!buf?.sensitivity && buf.sensitivity !== 0;
    const unit = amplitudeUnit(amplitudeMode, buf?.inputUnits, canPhysical);

    let min = statsMap.get(key)?.min ?? null;
    let max = statsMap.get(key)?.max ?? null;
    if ((min == null || max == null) && buf) {
      const win = buf.copyAlignedWindow(view.endMs, durationSec);
      let samples = win.samples;
      if (bandPass && samples.length) {
        samples = applyBandPassCached(
          key,
          samples,
          win.sampleRate,
          win.windowStartMs,
          win.windowEndMs,
          bandPass.fminHz,
          bandPass.fmaxHz,
        );
      }
      if (samples.length) {
        min = Infinity;
        max = -Infinity;
        for (let i = 0; i < samples.length; i++) {
          let v = samples[i]!;
          if (canPhysical) v = v / buf.sensitivity!;
          if (v < min) min = v;
          if (v > max) max = v;
        }
        if (!Number.isFinite(min) || !Number.isFinite(max)) {
          min = null;
          max = null;
        }
      }
    }

    const hasData = min != null && max != null && Number.isFinite(min) && Number.isFinite(max);
    const rangeLabel = hasData
      ? `${fmtAmp(min)} / ${fmtAmp(max)} ${unit}`
      : "데이터 없음";

    return {
      key,
      scnl: p.scnl,
      gapCount: gaps.length,
      rangeLabel,
      hasData,
    };
  });

  return { overlays, timeAxis };
}

function liveView(
  panels: { scnl: SCNL }[],
  durationSec: number,
  anchor: XAxisRightAnchor,
): ViewWindow {
  const endMs = resolveWindowEndMs(anchor, panels);
  return { startMs: endMs - durationSec * 1000, endMs };
}

export function WaveformStack() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<SharedWaveformRenderer | null>(null);
  const panels = useAppStore((s) => s.panels);
  const settings = useAppStore((s) => s.settings);
  const globalPaused = useAppStore((s) => s.globalPaused);
  const selected = useAppStore((s) => s.selectedPanelKey);
  const setSelected = useAppStore((s) => s.setSelectedPanel);
  const removePanel = useAppStore((s) => s.removePanel);
  const reorder = useAppStore((s) => s.reorderPanels);
  const { previewTheme, previewMode } = useTheme();
  const plotBg = useMemo(
    () => readPlotBackgroundHex(previewTheme, previewMode),
    [previewMode, previewTheme],
  );
  const waveformColors = useMemo(
    () => getThemeWaveformColors(previewTheme, previewMode),
    [previewMode, previewTheme],
  );
  const [overlays, setOverlays] = useState<PanelOverlay[]>([]);
  const [timeAxis, setTimeAxis] = useState<TimeAxisLabels>({
    startLabel: "--:--:--",
    endLabel: "--:--:--",
    ticks: [],
  });
  const [analysisModes, setAnalysisModes] = useState<Map<string, AnalysisMode>>(
    () => new Map(),
  );
  /** 일시정지 중 줌/팬 뷰 스택 (마지막이 현재 뷰) */
  const [zoomStack, setZoomStack] = useState<ViewWindow[]>([]);
  const [displayView, setDisplayView] = useState<ViewWindow | null>(null);
  const [dragSel, setDragSel] = useState<{ left: number; width: number } | null>(null);

  const dragIndex = useRef<number | null>(null);
  const panelsRef = useRef(panels);
  const settingsRef = useRef(settings);
  const globalPausedRef = useRef(globalPaused);
  const analysisModesRef = useRef(analysisModes);
  const zoomStackRef = useRef(zoomStack);
  /** 일시정지 진입 시점의 기본(줌 전) 창 */
  const frozenBaseRef = useRef<ViewWindow | null>(null);
  const pointersRef = useRef<Map<number, PointerSample>>(new Map());
  const gestureRef = useRef<Gesture | null>(null);
  const lastTapRef = useRef<{ t: number; x: number; y: number } | null>(null);
  const skipClickRef = useRef(false);

  panelsRef.current = panels;
  settingsRef.current = settings;
  globalPausedRef.current = globalPaused;
  analysisModesRef.current = analysisModes;
  zoomStackRef.current = zoomStack;

  const resolveView = (
    p: typeof panels,
    s: NonNullable<typeof settings>,
    paused: boolean,
    stack: ViewWindow[],
  ): ViewWindow => {
    if (paused) {
      if (stack.length) return stack[stack.length - 1]!;
      if (frozenBaseRef.current) return frozenBaseRef.current;
    }
    return liveView(p, s.durationSec, s.xAxisRightAnchor || "lastData");
  };

  const refreshOverlays = (
    p: typeof panels,
    view: ViewWindow,
    amplitudeMode: "raw" | "physical",
    bandPass?: { fminHz: number; fmaxHz: number } | null,
  ) => {
    const built = buildOverlays(
      p,
      view,
      amplitudeMode,
      rendererRef.current?.getLastStats(),
      bandPass,
    );
    setOverlays(built.overlays);
    setTimeAxis(built.timeAxis);
    setDisplayView(view);
  };

  const drawFrame = (
    p: typeof panels,
    s: NonNullable<typeof settings>,
    modes: Map<string, AnalysisMode>,
    stack: ViewWindow[] = zoomStackRef.current,
  ) => {
    const paused = globalPausedRef.current;
    const view = resolveView(p, s, paused, stack);
    const durationSec = viewDurationSec(view);
    const specs = p.map((x) => ({
      scnl: x.scnl,
      hideWave: modes.has(scnlKey(x.scnl)),
    }));
    const bp = resolveBandPass(
      s.bandPassEnabled,
      s.bandPassPresetId,
      s.bandPassPresets,
    );
    if (p.length) {
      rendererRef.current?.draw(
        specs,
        durationSec,
        s.amplitudeMode,
        view.endMs,
        s.xAxisRightAnchor || "lastData",
        s.yScaleMode || "auto",
        bp,
      );
    }
    refreshOverlays(p, view, s.amplitudeMode, bp);
  };

  const cycleAnalysis = (key: string) => {
    setAnalysisModes((prev) => {
      const next = new Map(prev);
      const cur = next.get(key);
      if (cur === "fft") next.set(key, "spec");
      else if (cur === "spec") next.delete(key);
      else next.set(key, "fft");
      return next;
    });
  };

  // 일시정지 진입/해제: 기본 창 고정 및 줌 초기화
  useEffect(() => {
    if (!settings) return;
    if (globalPaused) {
      const base = liveView(
        panelsRef.current,
        settings.durationSec,
        settings.xAxisRightAnchor || "lastData",
      );
      frozenBaseRef.current = base;
      setZoomStack([]);
      zoomStackRef.current = [];
      drawFrame(panelsRef.current, settings, analysisModesRef.current, []);
    } else {
      frozenBaseRef.current = null;
      setZoomStack([]);
      zoomStackRef.current = [];
      setDragSel(null);
      gestureRef.current = null;
      pointersRef.current.clear();
      lastTapRef.current = null;
      drawFrame(panelsRef.current, settings, analysisModesRef.current, []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [globalPaused]);

  useEffect(() => {
    const keys = new Set(panels.map((p) => scnlKey(p.scnl)));
    setAnalysisModes((prev) => {
      let changed = false;
      const next = new Map<string, AnalysisMode>();
      for (const [k, v] of prev) {
        if (keys.has(k)) next.set(k, v);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [panels]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const r = new SharedWaveformRenderer();
    r.attach(canvas, readPlotBackgroundHex(previewTheme, previewMode));
    rendererRef.current = r;

    const redraw = () => {
      const s = settingsRef.current;
      const p = panelsRef.current;
      if (!s || !rendererRef.current) return;
      rendererRef.current.resize(true);
      drawFrame(p, s, analysisModesRef.current);
    };

    const onWinResize = () => redraw();
    window.addEventListener("resize", onWinResize);

    let ro: ResizeObserver | null = null;
    if (wrapRef.current && typeof ResizeObserver !== "undefined") {
      let t: number | null = null;
      ro = new ResizeObserver(() => {
        if (t != null) window.clearTimeout(t);
        t = window.setTimeout(redraw, 50);
      });
      ro.observe(wrapRef.current);
    }

    return () => {
      window.removeEventListener("resize", onWinResize);
      ro?.disconnect();
      r.dispose();
      rendererRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!settings || !rendererRef.current) return;
    const specs = panels.map((p) => ({
      scnl: p.scnl,
      hideWave: analysisModes.has(scnlKey(p.scnl)),
    }));
    rendererRef.current.setBackground(readPlotBackgroundHex(previewTheme, previewMode));
    rendererRef.current.setPanels(specs, waveformColors);
    drawFrame(panels, settings, analysisModes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panels, settings, analysisModes, previewTheme, previewMode, waveformColors, plotBg]);

  useEffect(() => {
    if (!settings) return;
    const id = window.setInterval(() => {
      if (globalPaused) {
        // 일시정지: 라이브 스크롤 중지, 현재(줌) 뷰 오버레이만 갱신
        const view = resolveView(
          panels,
          settings,
          true,
          zoomStackRef.current,
        );
        refreshOverlays(
          panels,
          view,
          settings.amplitudeMode,
          resolveBandPass(
            settings.bandPassEnabled,
            settings.bandPassPresetId,
            settings.bandPassPresets,
          ),
        );
        return;
      }
      drawFrame(panels, settings, analysisModes);
    }, settings.refreshIntervalMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panels, settings, globalPaused, analysisModes, zoomStack]);

  const clientXToRatio = (clientX: number) => {
    const el = wrapRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0) return 0;
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  };

  const wrapWidth = () => wrapRef.current?.getBoundingClientRect().width || 1;

  const commitView = (view: ViewWindow) => {
    const s = settingsRef.current;
    const p = panelsRef.current;
    const base = frozenBaseRef.current;
    if (!s || !globalPausedRef.current || !base) return;
    const clamped = clampViewToBase(view, base);
    if (viewsNearlyEqual(clamped, base)) {
      zoomStackRef.current = [];
      setZoomStack([]);
      drawFrame(p, s, analysisModesRef.current, []);
      return;
    }
    // 연속 제스처(핀치/팬)는 스택 최상단을 갱신
    const stack = [clamped];
    zoomStackRef.current = stack;
    setZoomStack(stack);
    drawFrame(p, s, analysisModesRef.current, stack);
  };

  const pushBoxZoom = (x0: number, x1: number) => {
    const s = settingsRef.current;
    const p = panelsRef.current;
    const base = frozenBaseRef.current;
    if (!s || !globalPausedRef.current || !base) return;
    const view = resolveView(p, s, true, zoomStackRef.current);
    const r0 = Math.min(x0, x1);
    const r1 = Math.max(x0, x1);
    if (r1 - r0 < 0.02) return;
    const span = view.endMs - view.startMs;
    let startMs = view.startMs + r0 * span;
    let endMs = view.startMs + r1 * span;
    if (endMs - startMs < MIN_ZOOM_SEC * 1000) {
      const mid = (startMs + endMs) / 2;
      startMs = mid - (MIN_ZOOM_SEC * 1000) / 2;
      endMs = mid + (MIN_ZOOM_SEC * 1000) / 2;
    }
    const next = clampViewToBase({ startMs, endMs }, base);
    if (viewsNearlyEqual(next, base)) return;
    const stack = [...zoomStackRef.current, next];
    zoomStackRef.current = stack;
    setZoomStack(stack);
    drawFrame(p, s, analysisModesRef.current, stack);
  };

  const resetZoom = () => {
    const s = settingsRef.current;
    const p = panelsRef.current;
    if (!s || !globalPausedRef.current) return;
    zoomStackRef.current = [];
    setZoomStack([]);
    setDragSel(null);
    drawFrame(p, s, analysisModesRef.current, []);
  };

  const pointerDist = (a: PointerSample, b: PointerSample) => {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return Math.hypot(dx, dy);
  };

  const beginPinch = () => {
    const s = settingsRef.current;
    const p = panelsRef.current;
    if (!s) return;
    const pts = [...pointersRef.current.entries()];
    if (pts.length < 2) return;
    const [id0, a] = pts[0]!;
    const [id1, b] = pts[1]!;
    const dist = pointerDist(a, b);
    if (dist < PINCH_MIN_DIST_PX) return;
    const centerRatio = clientXToRatio((a.x + b.x) / 2);
    const origin = resolveView(p, s, true, zoomStackRef.current);
    gestureRef.current = {
      kind: "pinch",
      id0,
      id1,
      startDist: dist,
      origin,
      centerRatio,
    };
    setDragSel(null);
    lastTapRef.current = null;
  };

  const applyPinch = () => {
    const g = gestureRef.current;
    const base = frozenBaseRef.current;
    if (!g || g.kind !== "pinch" || !base) return;
    const a = pointersRef.current.get(g.id0);
    const b = pointersRef.current.get(g.id1);
    if (!a || !b) return;
    const dist = Math.max(PINCH_MIN_DIST_PX, pointerDist(a, b));
    // 핀치 아웃(거리↑) → scale↓ → 시간창 축소 = 줌인
    const scale = g.startDist / dist;
    const originDur = Math.max(1, g.origin.endMs - g.origin.startMs);
    const baseDur = Math.max(1, base.endMs - base.startMs);
    let newDur = originDur * scale;
    newDur = Math.min(baseDur, Math.max(MIN_ZOOM_SEC * 1000, newDur));
    const centerMs = g.origin.startMs + g.centerRatio * originDur;
    const startMs = centerMs - g.centerRatio * newDur;
    commitView({ startMs, endMs: startMs + newDur });
  };

  const applyPan = (clientX: number) => {
    const g = gestureRef.current;
    const base = frozenBaseRef.current;
    if (!g || g.kind !== "pan" || !base) return;
    const w = wrapWidth();
    const deltaRatio = (clientX - g.startClientX) / w;
    const span = g.origin.endMs - g.origin.startMs;
    // 손가락을 오른쪽으로 → 더 과거(왼쪽) 시간이 보이도록
    const startMs = g.origin.startMs - deltaRatio * span;
    commitView({ startMs, endMs: startMs + span });
  };

  const onWavePointerDown = (e: React.PointerEvent) => {
    if (!globalPausedRef.current) return;
    if (e.pointerType !== "touch" && e.button !== 0) return;

    pointersRef.current.set(e.pointerId, {
      x: e.clientX,
      y: e.clientY,
      type: e.pointerType,
    });
    try {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    } catch {
      /* ignore */
    }

    const count = pointersRef.current.size;
    const isTouch = e.pointerType === "touch";

    if (count >= 2 && isTouch) {
      e.preventDefault();
      beginPinch();
      return;
    }

    if (gestureRef.current?.kind === "pinch") return;

    // 터치: 줌된 상태에서만 한 손가락 팬. 줌 전은 핀치/더블탭만.
    if (isTouch) {
      e.preventDefault();
      if (zoomStackRef.current.length > 0) {
        const s = settingsRef.current;
        const p = panelsRef.current;
        if (!s) return;
        gestureRef.current = {
          kind: "pan",
          pointerId: e.pointerId,
          startClientX: e.clientX,
          origin: resolveView(p, s, true, zoomStackRef.current),
        };
      } else {
        gestureRef.current = null;
      }
      return;
    }

    // 마우스(데스크톱): 드래그 박스 줌인
    e.preventDefault();
    const ratio = clientXToRatio(e.clientX);
    gestureRef.current = {
      kind: "box-zoom",
      pointerId: e.pointerId,
      startX: ratio,
      curX: ratio,
      moved: false,
    };
    setDragSel({ left: ratio * 100, width: 0 });
  };

  const onWavePointerMove = (e: React.PointerEvent) => {
    if (!pointersRef.current.has(e.pointerId)) return;
    pointersRef.current.set(e.pointerId, {
      x: e.clientX,
      y: e.clientY,
      type: e.pointerType,
    });

    const g = gestureRef.current;
    if (!g) return;

    if (g.kind === "pinch") {
      e.preventDefault();
      applyPinch();
      return;
    }

    if (g.kind === "pan" && e.pointerId === g.pointerId) {
      e.preventDefault();
      applyPan(e.clientX);
      return;
    }

    if (g.kind === "box-zoom" && e.pointerId === g.pointerId) {
      const ratio = clientXToRatio(e.clientX);
      g.curX = ratio;
      const w = wrapWidth();
      if (Math.abs(ratio - g.startX) * w >= ZOOM_DRAG_THRESHOLD_PX) {
        g.moved = true;
      }
      setDragSel({
        left: Math.min(g.startX, ratio) * 100,
        width: Math.abs(ratio - g.startX) * 100,
      });
    }
  };

  const onWavePointerUp = (e: React.PointerEvent) => {
    const sample = pointersRef.current.get(e.pointerId);
    pointersRef.current.delete(e.pointerId);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    } catch {
      /* ignore */
    }

    const g = gestureRef.current;

    if (g?.kind === "pinch") {
      if (e.pointerId === g.id0 || e.pointerId === g.id1) {
        gestureRef.current = null;
        // 남은 한 손가락으로는 즉시 팬 시작하지 않음
        skipClickRef.current = true;
        lastTapRef.current = null;
      }
      if (pointersRef.current.size >= 2) beginPinch();
      return;
    }

    if (g?.kind === "pan" && e.pointerId === g.pointerId) {
      const panMoved =
        Math.abs(e.clientX - g.startClientX) >= ZOOM_DRAG_THRESHOLD_PX;
      gestureRef.current = null;
      if (panMoved) {
        skipClickRef.current = true;
        lastTapRef.current = null;
        return;
      }
      // 거의 안 움직인 탭 → 더블탭 판정으로 진행
    } else if (g?.kind === "box-zoom" && e.pointerId === g.pointerId) {
      gestureRef.current = null;
      setDragSel(null);
      if (!globalPausedRef.current) return;
      if (g.moved) {
        pushBoxZoom(g.startX, g.curX);
        skipClickRef.current = true;
        lastTapRef.current = null;
        return;
      }
    } else if (!g) {
      gestureRef.current = null;
      setDragSel(null);
    }

    if (!globalPausedRef.current || !sample) return;

    // 더블탭(터치) / 더블클릭(마우스) → 파형(줌) 초기화

    const now = performance.now();
    const prev = lastTapRef.current;
    if (
      prev &&
      now - prev.t < ZOOM_DBLCLICK_MS &&
      Math.hypot(e.clientX - prev.x, e.clientY - prev.y) < TAP_MAX_MOVE_PX * 2
    ) {
      lastTapRef.current = null;
      skipClickRef.current = true;
      resetZoom();
    } else {
      lastTapRef.current = { t: now, x: e.clientX, y: e.clientY };
    }
  };

  return (
    <div
      className="wave-stack"
      style={{
        ["--plot-selection" as string]: waveformColors.selectionColor,
      }}
    >
      <div
        className={`wave-canvas-wrap ${globalPaused ? "paused-gestures" : ""}`}
        ref={wrapRef}
        onPointerDown={onWavePointerDown}
        onPointerMove={onWavePointerMove}
        onPointerUp={onWavePointerUp}
        onPointerCancel={onWavePointerUp}
      >
        <div
          className="wave-canvas-inner"
          style={{
            minHeight:
              panels.length > 0
                ? `max(100%, ${panels.length * PANEL_ROW_MIN_PX}px)`
                : "100%",
          }}
        >
          <canvas ref={canvasRef} />
          {panels.length > 0 && timeAxis.ticks.length > 0 && (
            <div className="wave-x-grid" aria-hidden="true">
              {timeAxis.ticks.map((t) => (
                <div
                  key={t.ms}
                  className="wave-x-grid-line"
                  style={{ left: `${t.x * 100}%` }}
                />
              ))}
            </div>
          )}
          {dragSel && dragSel.width > 0 && (
            <div
              className="wave-zoom-sel"
              style={{ left: `${dragSel.left}%`, width: `${dragSel.width}%` }}
              aria-hidden="true"
            />
          )}
          {panels.length === 0 && (
            <div className="empty-wave">채널을 선택하고 Plot 하거나 레이아웃을 불러오세요.</div>
          )}
          {panels.length > 0 && (
            <div className="wave-overlays">
              {overlays.map((o, idx) => {
                const mode = analysisModes.get(o.key);
                const isFft = mode === "fft";
                const isSpec = mode === "spec";
                const isAnalysis = isFft || isSpec;
                return (
                  <div
                    key={o.key}
                    className={`wave-panel-overlay ${selected === o.key ? "selected" : ""} ${
                      isAnalysis ? "fft-mode" : ""
                    } ${
                      globalPaused
                        ? zoomStack.length > 0
                          ? "paused-zoom paused-pan"
                          : "paused-zoom"
                        : ""
                    }`}
                    draggable={!isAnalysis && !globalPaused}
                    title={
                      globalPaused
                        ? "모바일: 핀치 아웃 줌인 · 핀치 인 줌아웃 · 더블탭 초기화 · 줌 후 드래그 이동 / 데스크톱: 드래그 줌인 · 더블클릭 초기화"
                        : "우클릭: 웨이브폼 → FFT → Spectrogram"
                    }
                    onDragStart={() => {
                      dragIndex.current = idx;
                    }}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      if (dragIndex.current == null) return;
                      reorder(dragIndex.current, idx);
                      dragIndex.current = null;
                    }}
                    onClick={() => {
                      if (skipClickRef.current) {
                        skipClickRef.current = false;
                        return;
                      }
                      setSelected(o.key);
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setSelected(o.key);
                      cycleAnalysis(o.key);
                    }}
                  >
                    {isFft && displayView && (
                      <PanelFftCanvas
                        panelKey={o.key}
                        windowEndMs={displayView.endMs}
                        durationSec={viewDurationSec(displayView)}
                      />
                    )}
                    {isSpec && displayView && (
                      <PanelSpectrogramCanvas
                        panelKey={o.key}
                        windowEndMs={displayView.endMs}
                        durationSec={viewDurationSec(displayView)}
                      />
                    )}
                    <div className="wave-scnl-badge" title={scnlKey(o.scnl)}>
                      <div className="wave-scnl-name">
                        {scnlBadge(o.scnl)}
                        {isFft && <span className="fft-badge"> FFT</span>}
                        {isSpec && <span className="fft-badge"> SPEC</span>}
                      </div>
                      {!isAnalysis && (
                        <div
                          className={`wave-scnl-minmax ${o.hasData ? "" : "no-data"}`.trim()}
                        >
                          {o.rangeLabel}
                        </div>
                      )}
                    </div>
                    <div className="wave-panel-actions">
                      {o.gapCount > 0 && <span className="gap-badge">GAP {o.gapCount}</span>}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          removePanel(o.key);
                        }}
                      >
                        ✕
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
      {panels.length > 0 && (
        <div className="wave-time-axis" aria-hidden="true">
          <span className="wave-time start">{timeAxis.startLabel}</span>
          {timeAxis.ticks
            .filter((t) => !t.edge)
            .map((t) => (
              <span
                key={t.ms}
                className="wave-time tick"
                style={{ left: `${t.x * 100}%` }}
              >
                {t.label}
              </span>
            ))}
          <span className="wave-time end">{timeAxis.endLabel}</span>
        </div>
      )}
    </div>
  );
}
