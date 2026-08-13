import { useEffect, useRef } from "react";
import { useAppStore } from "../../store/appStore";
import { bufferStore } from "../../buffer/ringBuffer";
import { computeFftDb } from "../../render/fft";
import { applyBandPassCached } from "../../render/bandpass";
import { resolveBandPass } from "../../realtime/bandPassPresets";

type Props = {
  panelKey: string;
  windowEndMs: number;
  durationSec: number;
};

function log10(v: number): number {
  return Math.log10(Math.max(v, 1e-20));
}

/** 로그 주파수 축용 눈금 (1–2–5 × 10^n) */
function logFreqTicks(fMin: number, fMax: number): number[] {
  if (!(fMin > 0) || !(fMax > fMin)) return [];
  const ticks: number[] = [];
  const exp0 = Math.floor(log10(fMin));
  const exp1 = Math.ceil(log10(fMax));
  for (let e = exp0; e <= exp1; e++) {
    for (const m of [1, 2, 5]) {
      const f = m * 10 ** e;
      if (f >= fMin * 0.999 && f <= fMax * 1.001) ticks.push(f);
    }
  }
  return ticks;
}

function fmtFreq(f: number): string {
  if (f >= 100) return f.toFixed(0);
  if (f >= 10) return f.toFixed(1);
  if (f >= 1) return f.toFixed(2);
  return f.toPrecision(2);
}

/** 패널 행 위에 그리는 FFT — Log Frequency × Log Power (dB) */
export function PanelFftCanvas({ panelKey, windowEndMs, durationSec }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const settings = useAppStore((s) => s.settings);
  const globalPaused = useAppStore((s) => s.globalPaused);

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
      ctx.fillStyle = "#0b1016";
      ctx.fillRect(0, 0, w, h);

      const buf = bufferStore.get(panelKey);
      if (!buf) {
        ctx.fillStyle = "#9aa7b5";
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
      const sr = win.sampleRate || buf.sampleRate;
      const { freqs, db } = computeFftDb(samples, sr);
      if (!freqs.length) {
        ctx.fillStyle = "#9aa7b5";
        ctx.font = "12px sans-serif";
        ctx.fillText("FFT 샘플 부족", 10, 20);
        return;
      }

      // DC(0 Hz)는 log 축에서 제외 — 첫 양의 주파수부터
      let i0 = 0;
      while (i0 < freqs.length && freqs[i0]! <= 0) i0++;
      if (i0 >= freqs.length - 1) {
        ctx.fillStyle = "#9aa7b5";
        ctx.font = "12px sans-serif";
        ctx.fillText("유효 주파수 없음", 10, 20);
        return;
      }

      const fMin = Math.max(freqs[i0]!, 1e-3);
      const fMax = Math.max(freqs[freqs.length - 1]!, fMin * 10);
      const logFMin = log10(fMin);
      const logFMax = log10(fMax);
      const logFSpan = Math.max(1e-9, logFMax - logFMin);

      let minDb = Infinity;
      let maxDb = -Infinity;
      for (let i = i0; i < db.length; i++) {
        const v = db[i]!;
        if (v < minDb) minDb = v;
        if (v > maxDb) maxDb = v;
      }
      if (!Number.isFinite(minDb) || !Number.isFinite(maxDb) || minDb === maxDb) {
        minDb = (Number.isFinite(minDb) ? minDb : -120) - 1;
        maxDb = (Number.isFinite(maxDb) ? maxDb : -20) + 1;
      }
      // 약간의 여유
      const dbPad = Math.max(1, (maxDb - minDb) * 0.05);
      minDb -= dbPad;
      maxDb += dbPad;
      const dbSpan = Math.max(1e-6, maxDb - minDb);

      const padT = 22;
      const padB = 18;
      const padL = 36;
      const padR = 8;
      const plotH = Math.max(8, h - padT - padB);
      const plotW = Math.max(8, w - padL - padR);

      const xOfF = (f: number) =>
        padL + ((log10(f) - logFMin) / logFSpan) * plotW;
      const yOfDb = (v: number) =>
        padT + plotH - ((v - minDb) / dbSpan) * plotH;

      // 로그 주파수 그리드
      ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
      ctx.lineWidth = 1;
      for (const f of logFreqTicks(fMin, fMax)) {
        const x = xOfF(f);
        ctx.beginPath();
        ctx.moveTo(x, padT);
        ctx.lineTo(x, padT + plotH);
        ctx.stroke();
      }

      // 스펙트럼 (Log F × Log Power dB)
      ctx.strokeStyle = settings.waveformColors.selectionColor;
      ctx.lineWidth = 1.25;
      ctx.beginPath();
      let started = false;
      for (let i = i0; i < db.length; i++) {
        const f = freqs[i]!;
        if (!(f > 0)) continue;
        const x = xOfF(f);
        const y = yOfDb(db[i]!);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();

      // 제목 / 축 라벨
      ctx.fillStyle = "rgba(235, 240, 246, 0.9)";
      ctx.font = "11px sans-serif";
      ctx.textAlign = "left";
      ctx.fillText("FFT  Log F · Log Power (dB)", padL, 14);

      ctx.fillStyle = "rgba(154, 167, 181, 0.95)";
      ctx.font = "10px sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(`${maxDb.toFixed(0)}`, padL - 4, padT + 8);
      ctx.fillText(`${minDb.toFixed(0)}`, padL - 4, padT + plotH);

      ctx.textAlign = "left";
      ctx.fillText(fmtFreq(fMin), padL, h - 4);
      ctx.textAlign = "right";
      ctx.fillText(`${fmtFreq(fMax)} Hz`, w - padR, h - 4);
      ctx.textAlign = "left";
    };

    paint();
    if (globalPaused) return;
    const id = window.setInterval(paint, Math.max(200, settings.refreshIntervalMs));
    return () => window.clearInterval(id);
  }, [panelKey, settings, globalPaused, windowEndMs, durationSec]);

  return <canvas ref={canvasRef} className="panel-fft-canvas" />;
}
