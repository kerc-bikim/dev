import { useEffect, useMemo, useRef } from "react";
import { useAppStore } from "../../store/appStore";
import { bufferStore } from "../../buffer/ringBuffer";
import { applyBandPassCached } from "../../render/bandpass";
import { resolveBandPass } from "../../realtime/bandPassPresets";
import {
  computeSpectrogram,
  finitePercentile,
  jetRgb,
  spectrogramFreqRange,
  spectrogramFreqTicks,
} from "../../render/spectrogram";
import { sanitizeSpectrogramSettings } from "../../render/spectrogramSettings";
import { useTheme } from "@/theme/ThemeProvider";
import { readPlotBackgroundHex } from "@/theme/theme";

type Props = {
  panelKey: string;
  windowEndMs: number;
  durationSec: number;
};

function cssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "").trim();
  if (h.length === 3) {
    return [
      parseInt(h[0]! + h[0]!, 16) || 0,
      parseInt(h[1]! + h[1]!, 16) || 0,
      parseInt(h[2]! + h[2]!, 16) || 0,
    ];
  }
  if (h.length >= 6) {
    return [
      parseInt(h.slice(0, 2), 16) || 0,
      parseInt(h.slice(2, 4), 16) || 0,
      parseInt(h.slice(4, 6), 16) || 0,
    ];
  }
  return [0, 0, 0];
}

function fmtFreq(f: number): string {
  if (Math.abs(f - Math.round(f)) < 1e-6 && f >= 1) return String(Math.round(f));
  if (f >= 100) return f.toFixed(0);
  if (f >= 10) return f.toFixed(1);
  if (f >= 1) return f.toFixed(2);
  return f.toPrecision(2);
}

function sampleDb(
  db: Float32Array,
  frames: number,
  bins: number,
  fx: number,
  fy: number,
): number {
  const x0 = Math.min(frames - 1, Math.max(0, Math.floor(fx)));
  const y0 = Math.min(bins - 1, Math.max(0, Math.floor(fy)));
  const x1 = Math.min(frames - 1, x0 + 1);
  const y1 = Math.min(bins - 1, y0 + 1);
  const tx = fx - x0;
  const ty = fy - y0;
  const v00 = db[x0 * bins + y0]!;
  const v10 = db[x1 * bins + y0]!;
  const v01 = db[x0 * bins + y1]!;
  const v11 = db[x1 * bins + y1]!;
  return v00 * (1 - tx) * (1 - ty) + v10 * tx * (1 - ty) + v01 * (1 - tx) * ty + v11 * tx * ty;
}

/** 패널 행 위에 그리는 Spectrogram — Time × Frequency, jet colormap */
export function PanelSpectrogramCanvas({ panelKey, windowEndMs, durationSec }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const settings = useAppStore((s) => s.settings);
  const globalPaused = useAppStore((s) => s.globalPaused);
  const { previewTheme, previewMode } = useTheme();
  const plotBg = useMemo(
    () => readPlotBackgroundHex(previewTheme, previewMode),
    [previewMode, previewTheme],
  );

  useEffect(() => {
    if (!settings) return;

    const paint = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const parent = canvas.parentElement;
      const ctx = canvas.getContext("2d");
      if (!ctx || !parent) return;

      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = parent.clientWidth || 400;
      const h = parent.clientHeight || 88;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = plotBg;
      ctx.fillRect(0, 0, w, h);
      const muted = cssVar("--muted-foreground", "#9aa7b5");
      const ink = cssVar("--foreground", "#ebf0f6");
      const [bgR, bgG, bgB] = hexToRgb(plotBg);

      const buf = bufferStore.get(panelKey);
      if (!buf) {
        ctx.fillStyle = muted;
        ctx.font = "12px sans-serif";
        ctx.fillText("데이터 없음", 10, 20);
        return;
      }

      const win = buf.copyAlignedWindow(windowEndMs, durationSec);
      let samples = win.samples;
      const bp = resolveBandPass(
        settings.bandPassEnabled,
        settings.bandPassPresetId,
        settings.bandPassPresets,
      );
      if (bp) {
        samples = applyBandPassCached(
          panelKey,
          samples,
          win.sampleRate || buf.sampleRate,
          win.windowStartMs,
          win.windowEndMs,
          bp.fminHz,
          bp.fmaxHz,
        );
      }
      const padT = 22;
      const padB = 6;
      const padL = 36;
      const barW = 10;
      const padR = 28;
      const plotH = Math.max(8, h - padT - padB);
      const plotW = Math.max(8, w - padL - padR);
      const iw = Math.max(1, Math.floor(plotW * dpr));
      const ih = Math.max(1, Math.floor(plotH * dpr));

      const sr = win.sampleRate || buf.sampleRate;
      const specCfg = sanitizeSpectrogramSettings(settings.spectrogram);
      const spec = computeSpectrogram(samples, sr, {
        ...specCfg,
        timeCols: Math.min(specCfg.maxFrames, plotW),
      });
      if (!spec.frames || !spec.bins) {
        ctx.fillStyle = muted;
        ctx.font = "12px sans-serif";
        ctx.fillText("스펙트로그램 샘플 부족", 10, 20);
        return;
      }

      const { fMin, fMax } = spectrogramFreqRange(sr);
      const fSpan = Math.max(1e-9, fMax - fMin);
      const df = spec.nfft > 0 ? sr / spec.nfft : fSpan;

      let minDb = finitePercentile(spec.db, 0.05);
      let maxDb = finitePercentile(spec.db, 0.95);
      if (!Number.isFinite(minDb) || !Number.isFinite(maxDb) || minDb === maxDb) {
        minDb = (Number.isFinite(minDb) ? minDb : -120) - 1;
        maxDb = (Number.isFinite(maxDb) ? maxDb : -20) + 1;
      }
      const dbSpan = Math.max(1e-6, maxDb - minDb);

      const tFirst = win.sampleStartMs + spec.timesSec[0]! * 1000;
      const tLast =
        win.sampleStartMs + spec.timesSec[spec.frames - 1]! * 1000;
      const tSpan = Math.max(1, tLast - tFirst);
      const winSpan = Math.max(1, win.windowEndMs - win.windowStartMs);

      const img = ctx.createImageData(iw, ih);
      const data = img.data;

      for (let py = 0; py < ih; py++) {
        const freq = fMin + (1 - (py + 0.5) / ih) * fSpan;
        const fy = freq / df;
        for (let px = 0; px < iw; px++) {
          const t = win.windowStartMs + ((px + 0.5) / iw) * winSpan;
          const i = (py * iw + px) * 4;
          if (t < tFirst || t > tLast) {
            data[i] = bgR;
            data[i + 1] = bgG;
            data[i + 2] = bgB;
            data[i + 3] = 255;
            continue;
          }
          const fx = ((t - tFirst) / tSpan) * (spec.frames - 1);
          const v = sampleDb(spec.db, spec.frames, spec.bins, fx, fy);
          const tCol = (v - minDb) / dbSpan;
          const [r, g, b] = jetRgb(tCol);
          data[i] = r;
          data[i + 1] = g;
          data[i + 2] = b;
          data[i + 3] = 255;
        }
      }

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.putImageData(img, Math.floor(padL * dpr), Math.floor(padT * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const barX = padL + plotW + 4;
      for (let y = 0; y < plotH; y++) {
        const tCol = 1 - y / Math.max(1, plotH - 1);
        const [r, g, b] = jetRgb(tCol);
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillRect(barX, padT + y, barW, 1);
      }

      ctx.fillStyle = ink;
      ctx.font = "11px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(`Spectrogram  ${fmtFreq(fMin)}–${fmtFreq(fMax)} Hz  jet`, padL, 14);

      ctx.fillStyle = muted;
      ctx.font = "10px sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(`${maxDb.toFixed(0)}`, w - 4, padT + 8);
      ctx.fillText(`${minDb.toFixed(0)}`, w - 4, padT + plotH);

      ctx.textAlign = "right";
      for (const f of spectrogramFreqTicks(fMax, plotH)) {
        const y = padT + plotH - ((f - fMin) / fSpan) * plotH;
        ctx.fillText(fmtFreq(f), padL - 4, y + 3);
      }
      ctx.textAlign = "left";
    };

    paint();
    if (globalPaused) return;
    const id = window.setInterval(paint, Math.max(200, settings.refreshIntervalMs));
    return () => window.clearInterval(id);
  }, [panelKey, settings, globalPaused, windowEndMs, durationSec, plotBg]);

  return <canvas ref={canvasRef} className="panel-fft-canvas" />;
}
